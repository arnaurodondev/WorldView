"""ExportTransactionsUseCase — stream a portfolio's transactions as CSV rows.

PLAN-0114 / T-W2-05 (FR-3: Transaction CSV Export).

WHY a separate use case rather than a flag on ListTransactionsUseCase:
- Export requires ALL matching transactions (no pagination), whereas List
  always paginates — different repository methods, different contract.
- The FIFO cost-basis replay done here is stateful across rows and would
  pollute the list use case's single-responsibility: enrichment + pagination.
- StreamingResponse requires an iterator/generator; keeping this logic in its
  own class keeps the API route thin and makes the use case unit-testable
  without a real HTTP response object.

Security notes:
- CSV injection guard: cells starting with ``=``, ``+``, ``-``, or ``@``
  are prefixed with a single quote (``'``) so spreadsheet apps do not
  interpret them as formulae (§12.1 of the PRD).
- ``portfolio_id`` and ``tenant_id`` / ``owner_id`` are validated by the
  repository before any rows are returned (same auth guard as all S1 reads).
- The FIFO replay is deterministic: same transaction history → same output
  regardless of wall-clock time.

R27: uses ``ReadOnlyUnitOfWork`` (read-only use case).
"""

from __future__ import annotations

import csv
import io
from collections import deque
from collections.abc import Iterator
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.enums import PortfolioKind, TradeSide, TransactionType
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.domain.entities.transaction import Transaction
    from portfolio.domain.value_objects import TransactionFilter

logger = get_logger(__name__)  # type: ignore[no-any-return]

# CSV column names in output order — matches PRD §5.1 FR-3 table.
_CSV_HEADERS = [
    "date",
    "ticker",
    "type",
    "trade_side",
    "quantity",
    "price",
    "fees",
    "currency",
    "total_value",
    "cost_basis_per_unit",
    "realized_pnl",
    "description",
]

# Transaction types that represent position changes for FIFO tracking.
# BUY/TRADE+BUY open lots; SELL/TRADE+SELL close lots.
# All others (DIVIDEND, DEPOSIT, WITHDRAWAL, FEE, INTEREST) are pass-through.
_POSITION_OPENING_TYPES: frozenset[TransactionType] = frozenset([TransactionType.BUY, TransactionType.TRADE])
_POSITION_CLOSING_TYPES: frozenset[TransactionType] = frozenset([TransactionType.SELL, TransactionType.TRADE])


def _is_buy(tx: Transaction) -> bool:
    """Return True when the transaction opens a position (increases quantity)."""
    if tx.transaction_type == TransactionType.TRADE:
        return tx.trade_side == TradeSide.BUY
    return tx.transaction_type == TransactionType.BUY


def _is_sell(tx: Transaction) -> bool:
    """Return True when the transaction closes a position (decreases quantity)."""
    if tx.transaction_type == TransactionType.TRADE:
        return tx.trade_side == TradeSide.SELL
    return tx.transaction_type == TransactionType.SELL


def _sanitize_csv_cell(value: str) -> str:
    """Prefix cells that could be interpreted as spreadsheet formulae.

    CSV injection (OWASP A03:2021): Excel/LibreOffice/Google Sheets treat
    cells starting with ``=``, ``+``, ``-``, or ``@`` as formula expressions.
    Prefixing with ``'`` makes the spreadsheet treat the value as literal text.

    WHY only these four characters: they are the only prefix triggers defined
    by the OWASP CSV Injection guidance.  Other special characters (commas,
    quotes) are already handled by the ``csv`` module's quoting logic.
    """
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _fmt_decimal(value: Decimal | None) -> str:
    """Format a Decimal to a fixed 8-decimal string, or empty string if None."""
    if value is None:
        return ""
    return f"{value:.8f}"


class ExportTransactionsUseCase:
    """Stream all matching transactions as CSV rows for download.

    Usage (in the API route):
        use_case = ExportTransactionsUseCase()
        async with uow:
            rows_iter = await use_case.execute(portfolio_id, owner_id, tenant_id, filter, uow)
        return StreamingResponse(rows_iter, media_type="text/csv", ...)

    The method builds a ``ticker`` lookup (same bounded ``list_all`` approach
    as ``ListTransactionsUseCase``) and runs an in-memory FIFO replay to
    compute ``cost_basis_per_unit`` and ``realized_pnl`` for each row.

    FIFO lot structure: ``_lots`` is a ``dict[instrument_id, deque[(qty, price)]]``.
    Lots are queued in chronological order (ASC); SELLs dequeue from the front
    (FIFO = first lot bought is the first lot sold).

    Thread safety: each call creates its own ``_lots`` dict — no shared state.
    """

    async def execute(
        self,
        portfolio_id: UUID,
        owner_id: UUID,
        tenant_id: UUID,
        tx_filter: TransactionFilter,
        uow: ReadOnlyUnitOfWork,
    ) -> Iterator[str]:
        """Fetch transactions, compute FIFO cost basis, yield CSV chunks.

        Returns an iterator of strings — each string is a complete CSV line
        (including the trailing newline written by ``csv.writer``).  The API
        route wraps this in a ``StreamingResponse`` to avoid buffering the
        entire export in memory.

        WHY Iterator[str] not AsyncGenerator: ``StreamingResponse`` in FastAPI
        accepts both sync iterables and async generators.  A sync iterator
        keeps this use case fully unit-testable without asyncio boilerplate.

        WHY ``tx_filter`` not ``filter``: ``filter`` is a Python builtin; using
        it as a parameter name shadows the builtin and triggers ruff A002.
        """
        # --- Auth + portfolio lookup ---
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to export this portfolio's transactions")

        # --- Fetch matching transactions (chronological, no pagination) ---
        # For ROOT portfolios we fan out across all sub-portfolios, then sort
        # chronologically in-process.  For single portfolios we use the direct
        # filtered method which orders ASC at the DB level.
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(owner_id, tenant_id)
            if not sub_ids:
                transactions = []
            else:
                # Collect from each sub-portfolio and merge-sort.
                # For export scale (5-year cap) this is acceptable in-process.
                all_txs: list[Transaction] = []
                for pid in sub_ids:
                    txs = await uow.transactions.list_all_for_portfolio_filtered(pid, tenant_id, tx_filter)
                    all_txs.extend(txs)
                transactions = sorted(all_txs, key=lambda t: (t.executed_at, t.created_at))
        else:
            transactions = await uow.transactions.list_all_for_portfolio_filtered(portfolio_id, tenant_id, tx_filter)

        # --- Instrument ticker lookup (same bounded pattern as ListTransactionsUseCase) ---
        instrument_ids = {tx.instrument_id for tx in transactions}
        if instrument_ids:
            all_instruments, _ = await uow.instruments.list_all(limit=10_000, offset=0)
            # instrument_id → (ticker, asset_class) — we only need ticker for CSV
            ticker_map: dict[UUID, str] = {
                inst.id: inst.symbol
                for inst in all_instruments
                if inst.id in instrument_ids and inst.symbol is not None
            }
        else:
            ticker_map = {}

        logger.info(
            "export_transactions_started",
            portfolio_id=str(portfolio_id),
            transaction_count=len(transactions),
            from_date=str(tx_filter.from_date),
            to_date=str(tx_filter.to_date),
        )

        # --- FIFO lot tracking ---
        # Structure: instrument_id → deque of (quantity: Decimal, price: Decimal)
        # One deque per instrument; FIFO = front of deque = oldest lot.
        lots: dict[UUID, deque[tuple[Decimal, Decimal]]] = {}

        # Build output rows in-process (list of dicts) then stream via csv module.
        rows: list[dict[str, str]] = []

        for tx in transactions:
            ticker = ticker_map.get(tx.instrument_id, "")
            total_value = tx.quantity * tx.price

            cost_basis_per_unit: Decimal | None = None
            realized_pnl: Decimal | None = None

            # --- FIFO: handle BUY-side (open lot) ---
            if _is_buy(tx):
                if tx.instrument_id not in lots:
                    lots[tx.instrument_id] = deque()
                lots[tx.instrument_id].append((tx.quantity, tx.price))

            # --- FIFO: handle SELL-side (close lots) ---
            elif _is_sell(tx):
                instrument_lots = lots.get(tx.instrument_id, deque())
                remaining_sell_qty = tx.quantity
                total_cost_of_sold_units = Decimal(0)
                units_matched = Decimal(0)

                while remaining_sell_qty > 0 and instrument_lots:
                    lot_qty, lot_price = instrument_lots[0]

                    if lot_qty <= remaining_sell_qty:
                        # Consume entire lot.
                        total_cost_of_sold_units += lot_qty * lot_price
                        units_matched += lot_qty
                        remaining_sell_qty -= lot_qty
                        instrument_lots.popleft()
                    else:
                        # Partial consumption of this lot.
                        total_cost_of_sold_units += remaining_sell_qty * lot_price
                        units_matched += remaining_sell_qty
                        # Update the remaining lot quantity in-place.
                        instrument_lots[0] = (lot_qty - remaining_sell_qty, lot_price)
                        remaining_sell_qty = Decimal(0)

                if units_matched > 0:
                    cost_basis_per_unit = total_cost_of_sold_units / units_matched
                    # realized_pnl = proceeds - cost.  Fees reduce proceeds for sells.
                    proceeds = tx.quantity * tx.price - tx.fees
                    realized_pnl = proceeds - total_cost_of_sold_units

            row = {
                "date": _sanitize_csv_cell(tx.executed_at.date().isoformat()),
                "ticker": _sanitize_csv_cell(ticker),
                "type": _sanitize_csv_cell(str(tx.transaction_type)),
                "trade_side": _sanitize_csv_cell(str(tx.trade_side) if tx.trade_side else ""),
                "quantity": _fmt_decimal(tx.quantity),
                "price": _fmt_decimal(tx.price),
                "fees": _fmt_decimal(tx.fees),
                "currency": _sanitize_csv_cell(tx.currency),
                "total_value": _fmt_decimal(total_value),
                "cost_basis_per_unit": _fmt_decimal(cost_basis_per_unit),
                "realized_pnl": _fmt_decimal(realized_pnl),
                "description": _sanitize_csv_cell(tx.description or ""),
            }
            rows.append(row)

        # --- Stream CSV output via csv.writer ---
        # WHY StringIO + csv.writer: the csv module handles quoting of commas
        # and embedded newlines correctly; we don't want to reproduce that logic.
        # We write one row at a time to the StringIO buffer, yield the resulting
        # string, then reset the buffer to avoid accumulating the entire file.

        def _iter_csv() -> Iterator[str]:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=_CSV_HEADERS, lineterminator="\r\n")
            writer.writeheader()
            yield buf.getvalue()

            for row in rows:
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=_CSV_HEADERS, lineterminator="\r\n")
                writer.writerow(row)
                yield buf.getvalue()

        return _iter_csv()
