"""Transaction API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    PaginatedResponse,
    RecordTransactionRequest,
    RecordTransactionResponse,
    TransactionListItem,
)
from portfolio.application.use_cases.export_transactions import ExportTransactionsUseCase
from portfolio.application.use_cases.read_models import ListTransactionsUseCase
from portfolio.application.use_cases.record_transaction import RecordTransactionCommand, RecordTransactionUseCase
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType
from portfolio.domain.value_objects import TransactionFilter

router = APIRouter(tags=["transactions"])


def _parse_transaction_types(transaction_type: list[str] | None) -> list[TransactionType]:
    """Convert raw string values from query params to ``TransactionType`` enums.

    PLAN-0114 / T-W2-04. Invalid values raise 422 (FastAPI handles validation
    for Query params, but we also guard here to return a clear message when
    the value is not in the enum).
    """
    if not transaction_type:
        return []
    result: list[TransactionType] = []
    for raw in transaction_type:
        try:
            result.append(TransactionType(raw.upper()))
        except ValueError:
            valid = ", ".join(t.value for t in TransactionType)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid transaction_type '{raw}'. Valid values: {valid}",
            ) from None
    return result


def _build_tx_filter(
    from_date: date | None,
    to_date: date | None,
    transaction_type: list[str] | None,
    ticker: str | None,
    limit: int,
    offset: int,
) -> TransactionFilter | None:
    """Build a ``TransactionFilter`` VO from query params, or return None.

    PLAN-0114 / T-W2-04. Returns None when no filter params are supplied so
    ``ListTransactionsUseCase`` falls through to the unfiltered code path
    (backward compatible). Raises HTTP 400 when the date range exceeds 5 years.
    """
    types = _parse_transaction_types(transaction_type)
    if from_date is None and to_date is None and not types and ticker is None:
        return None  # no filter — use original unfiltered path
    try:
        return TransactionFilter(
            from_date=from_date,
            to_date=to_date,
            transaction_types=types,
            ticker=ticker,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


def _extract_owner_id(request: Request) -> UUID:
    """Read user_id (owner) from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "user_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    return UUID(str(raw))


@router.post(
    "/transactions",
    response_model=RecordTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_transaction(
    body: RecordTransactionRequest,
    uow: UoWDep,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> RecordTransactionResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)

    # PLAN-0108: TRADE transactions derive direction from trade_side so the
    # frontend doesn't need to know the INFLOW/OUTFLOW convention.
    # All other transaction types still require an explicit direction field.
    if body.transaction_type == "TRADE":
        direction = TransactionDirection.INFLOW if body.trade_side == "BUY" else TransactionDirection.OUTFLOW
        trade_side = TradeSide(body.trade_side)  # type: ignore[arg-type]
    else:
        # The schema validator already ensures direction is non-None for non-TRADE,
        # but we provide a fallback to avoid a runtime AttributeError if direction
        # is absent from older clients (results in 422 via Pydantic before this point).
        direction = TransactionDirection(body.direction or "INFLOW")
        trade_side = None

    uc = RecordTransactionUseCase()
    result = await uc.execute(
        RecordTransactionCommand(
            tenant_id=x_tenant_id,
            portfolio_id=body.portfolio_id,
            owner_id=x_owner_id,
            instrument_id=body.instrument_id,
            transaction_type=TransactionType(body.transaction_type),
            direction=direction,
            trade_side=trade_side,
            quantity=body.quantity,
            price=body.price,
            fees=body.fees,
            currency=body.currency,
            executed_at=body.executed_at,
            external_ref=body.external_ref,
            idempotency_key=idempotency_key,
        ),
        uow,
    )
    t = result.transaction
    return RecordTransactionResponse(
        id=t.id,
        portfolio_id=t.portfolio_id,
        instrument_id=t.instrument_id,
        transaction_type=str(t.transaction_type),
        direction=str(t.direction),
        quantity=t.quantity,
        price=t.price,
        fees=t.fees,
        currency=t.currency,
        executed_at=t.executed_at,
        created_at=t.created_at,
        trade_side=str(t.trade_side) if t.trade_side else None,
    )


def _build_transaction_response(
    enriched: list,  # type: ignore[type-arg]  # list[EnrichedTransaction]
    total: int,
    limit: int,
    offset: int,
) -> PaginatedResponse[TransactionListItem]:
    """Shared serialisation for the flat and nested transaction endpoints.

    F-012: extracted so both ``GET /transactions`` (flat) and
    ``GET /portfolios/{id}/transactions`` (nested) emit identical bodies.
    F-205 (QA iter-2): now consumes ``EnrichedTransaction`` so the response
    carries ``ticker``/``name`` resolved from the local instruments cache.
    """
    return PaginatedResponse(
        items=[
            TransactionListItem(
                id=e.transaction.id,
                portfolio_id=e.transaction.portfolio_id,
                instrument_id=e.transaction.instrument_id,
                transaction_type=str(e.transaction.transaction_type),
                direction=str(e.transaction.direction),
                quantity=e.transaction.quantity,
                price=e.transaction.price,
                fees=e.transaction.fees,
                amount=e.transaction.amount,  # PLAN-0046 / BP-263 — surface SnapTrade cash amount
                currency=e.transaction.currency,
                # F-205: enrichment fields (None when instrument not in local cache).
                ticker=e.ticker,
                name=e.name,
                # PLAN-0053 T-D-4-02: asset_class for frontend badge.
                asset_class=e.asset_class,
                executed_at=e.transaction.executed_at,
                external_ref=e.transaction.external_ref,
                # P2-E: broker-supplied description (Alembic 0020). None for
                # historical rows and brokers that omit the field.
                description=e.transaction.description,
                created_at=e.transaction.created_at,
            )
            for e in enriched
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/transactions", response_model=PaginatedResponse[TransactionListItem])
async def list_transactions(
    uow: ReadUoWDep,
    request: Request,
    portfolio_id: UUID = Header(..., alias="X-Portfolio-ID"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    transaction_type: list[str] | None = Query(default=None),
    # max_length=20: tickers are rarely longer than 10 chars; caps ILIKE pattern size
    # to prevent expensive wildcard amplification on the transactions table.
    # pattern restricts to valid ticker characters — rejects injection attempts.
    ticker: str | None = Query(default=None, max_length=20, pattern=r"^[A-Z0-9.\^-]*$"),
) -> PaginatedResponse[TransactionListItem]:
    x_owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    # PLAN-0114 / T-W2-04: build filter if any param is supplied; else use
    # unfiltered path for backward compatibility.
    tx_filter = _build_tx_filter(from_date, to_date, transaction_type, ticker, limit, offset)
    uc = ListTransactionsUseCase()
    transactions, total = await uc.execute(
        portfolio_id, x_owner_id, x_tenant_id, uow, limit=limit, offset=offset, tx_filter=tx_filter
    )
    return _build_transaction_response(transactions, total, limit, offset)


# PLAN-0114 / T-W2-06: CSV export endpoint.
# IMPORTANT: this route MUST be declared BEFORE
# ``/portfolios/{portfolio_id}/transactions`` to prevent FastAPI from
# treating "export" as a UUID value for ``portfolio_id`` in the more
# general route below.
@router.get("/portfolios/{portfolio_id}/transactions/export")
async def export_transactions(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    transaction_type: list[str] | None = Query(default=None),
    # max_length=20 + pattern: especially important on the export path (limit=999_999)
    # where an expensive ILIKE pattern would scan the entire transactions table.
    ticker: str | None = Query(default=None, max_length=20, pattern=r"^[A-Z0-9.\^-]*$"),
) -> StreamingResponse:
    """Stream all matching transactions as a CSV file.

    PLAN-0114 / T-W2-06 (FR-3). The response is a ``StreamingResponse`` so
    large exports are not buffered in memory. FIFO cost-basis replay is done
    inside ``ExportTransactionsUseCase`` so the CSV carries ``cost_basis_per_unit``
    and ``realized_pnl`` columns per SELL row.

    Security: date range is capped at 5 years (1826 days) — a 400 is returned
    if exceeded. CSV injection guard: cells starting with ``=``, ``+``, ``-``,
    ``@`` are prefixed with ``'`` (OWASP A03:2021).
    """
    x_owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    types = _parse_transaction_types(transaction_type)
    try:
        tx_filter = TransactionFilter(
            from_date=from_date,
            to_date=to_date,
            transaction_types=types,
            ticker=ticker,
            # No limit/offset — export fetches everything.
            limit=999_999,
            offset=0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio_id=portfolio_id,
        owner_id=x_owner_id,
        tenant_id=x_tenant_id,
        tx_filter=tx_filter,
        uow=uow,
    )
    filename = f"transactions_{portfolio_id}"
    if from_date:
        filename += f"_{from_date}"
    if to_date:
        filename += f"_{to_date}"
    filename += ".csv"
    # SEC-106: use RFC 6266 filename* encoding (UTF-8 percent-encoded) alongside
    # the legacy filename= fallback for browsers that only understand RFC 2183.
    # WHY both: RFC 6266 §5 recommends the dual form for maximum compatibility.
    # The filename* parameter takes precedence in RFC 6266-aware browsers
    # (Chrome 20+, Firefox 20+, Safari 7+). Older/minimal clients fall back to
    # the quoted filename= form.
    # WHY this matters even though the current filename only contains ASCII safe
    # chars (UUID hex + ISO dates): future-proofing — if a portfolio name or
    # ticker with non-ASCII chars were ever added to the filename the quoted form
    # alone would malform the header.  filename* is always the correct approach.
    # NOTE: urllib.parse.quote() with safe='' percent-encodes everything except
    # letters/digits/_ . - ~ per RFC 3986 §2.3 — safe for header values.
    from urllib.parse import quote as _url_quote  # local import to keep module-level clean

    filename_encoded = _url_quote(filename, safe="")
    return StreamingResponse(
        csv_iter,
        media_type="text/csv",
        headers={
            "Content-Disposition": (f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename_encoded}"),
            # Defence-in-depth: prevent MIME-sniffing by Chromium-based browsers.
            # Although _sanitize_csv_cell guards against CSV injection, older
            # Chromium builds may treat a text/csv response as HTML if opened
            # inline without this header (OWASP A05:2021 Security Misconfiguration).
            "X-Content-Type-Options": "nosniff",
        },
    )


# F-012 (QA 2026-04-28): canonical REST-nested form. The flat
# ``/v1/transactions?portfolio_id=...`` path stays for backward compat
# (the dashboard / older clients still hit it), but the nested form
# matches the rest of the analytics surface (``/portfolios/{id}/exposure``,
# ``/value-history``, ``/risk-metrics``) so a strict OpenAPI consumer
# isn't forced to special-case transactions.
@router.get(
    "/portfolios/{portfolio_id}/transactions",
    response_model=PaginatedResponse[TransactionListItem],
)
async def list_transactions_nested(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    transaction_type: list[str] | None = Query(default=None),
    # Same ticker guard as GET /transactions — caps ILIKE amplification risk.
    ticker: str | None = Query(default=None, max_length=20, pattern=r"^[A-Z0-9.\^-]*$"),
) -> PaginatedResponse[TransactionListItem]:
    """Nested alias for ``GET /transactions?portfolio_id=...``.

    Keeps the API surface uniform across the portfolio analytics endpoints
    that already use the nested form. The flat endpoint remains as the
    canonical path during the transition. PLAN-0114 / T-W2-04: now accepts
    the same filter query params as the flat endpoint.
    """
    x_owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    tx_filter = _build_tx_filter(from_date, to_date, transaction_type, ticker, limit, offset)
    uc = ListTransactionsUseCase()
    transactions, total = await uc.execute(
        portfolio_id, x_owner_id, x_tenant_id, uow, limit=limit, offset=offset, tx_filter=tx_filter
    )
    return _build_transaction_response(transactions, total, limit, offset)
