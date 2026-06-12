"""Pydantic request/response schemas for the Portfolio API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_serializer, field_validator, model_validator

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated list response."""

    items: list[T]
    total: int
    limit: int
    offset: int


def _fmt_decimal(v: Decimal) -> str:
    """Serialize Decimal to 8-decimal-place string (matches DB Numeric(18,8))."""
    return f"{v:.8f}"


def _validate_currency(v: str) -> str:
    if not (len(v) == 3 and v.isupper() and v.isalpha()):
        raise ValueError(f"Currency must be a 3-letter uppercase code, got: {v!r}")
    return v


class TenantCreateRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class TenantResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime


class UserCreateRequest(BaseModel):
    tenant_id: UUID
    email: EmailStr = Field(max_length=254)  # RFC 5321 max


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    status: str
    created_at: datetime


class UserInternalResponse(BaseModel):
    """Response shape for GET /internal/v1/users/{user_id} (PRD-0016 §6.2)."""

    user_id: UUID
    tenant_id: UUID
    email_address: str
    username: str
    created_at: datetime


class PortfolioCreateRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    owner_user_id: UUID
    currency: str = "USD"

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        return _validate_currency(v)


class PortfolioResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    name: str
    currency: str
    status: str
    # PLAN-0046 Wave 3 / T-46-3-01: discriminator surfaced to clients so the
    # frontend can render the ROOT badge and disable delete. ``manual`` /
    # ``brokerage`` / ``root``. Field is required on the response — S1 always
    # populates ``kind`` once migration 0011 has been applied (default
    # backfilled to 'manual' for historical rows).
    kind: str
    created_at: datetime


class PortfolioRenameRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class RecordTransactionRequest(BaseModel):
    portfolio_id: UUID
    instrument_id: UUID
    # PLAN-0108: tightened from bare str to an exhaustive Literal so unknown
    # types yield 422 (Pydantic validation) instead of 500 (ValueError inside
    # the use case after the enum lookup fails with a KeyError/ValueError).
    transaction_type: Literal["BUY", "SELL", "DIVIDEND", "DEPOSIT", "WITHDRAWAL", "FEE", "INTEREST", "TRADE"]
    # PLAN-0108: direction is INFLOW/OUTFLOW; reject anything else at the
    # schema layer before it reaches the domain enum constructor.
    direction: Literal["INFLOW", "OUTFLOW"] | None = None
    # PLAN-0108: BUY/SELL side only for transaction_type=TRADE. The model
    # validator below enforces the coupling: TRADE requires trade_side,
    # non-TRADE must omit it (or pass null).
    trade_side: Literal["BUY", "SELL"] | None = None
    quantity: Decimal
    price: Decimal
    fees: Decimal = Decimal(0)
    currency: str
    executed_at: datetime
    external_ref: str | None = None

    @model_validator(mode="after")
    def validate_trade_side(self) -> RecordTransactionRequest:
        # WHY: TRADE transactions use trade_side to derive direction server-side
        # (BUY → INFLOW, SELL → OUTFLOW). Requiring trade_side here avoids a
        # silent 500 in the route handler when direction is None for TRADE rows.
        if self.transaction_type == "TRADE" and self.trade_side is None:
            raise ValueError("trade_side is required when transaction_type is TRADE")
        return self

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        return _validate_currency(v)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        if v <= Decimal(0):
            raise ValueError("quantity must be positive")
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: Decimal) -> Decimal:
        if v <= Decimal(0):
            raise ValueError("price must be positive")
        return v


class RecordTransactionResponse(BaseModel):
    id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    transaction_type: str
    direction: str
    quantity: Decimal
    price: Decimal
    fees: Decimal
    currency: str
    executed_at: datetime
    created_at: datetime
    # PLAN-0108: echoed back so the frontend can display BUY/SELL without
    # needing to infer it from direction (which is INFLOW/OUTFLOW).
    trade_side: str | None = None

    @field_serializer("quantity", "price", "fees")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class HoldingResponse(BaseModel):
    id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    quantity: Decimal
    average_cost: Decimal
    currency: str
    # Enriched from instruments table via LEFT JOIN (None when instrument record absent)
    ticker: str | None = None
    name: str | None = None
    entity_id: UUID | None = None
    # 2026-06-10 (frontend-enhancement sprint, gap #1): asset_class joins the
    # enrichment set so the holdings table can render the ASSET column without
    # cross-referencing the transactions page (which only covers instruments
    # with a transaction on the current page — everything else showed "—").
    # Forward-compatible add (R11): nullable with default, never required.
    asset_class: str | None = None

    @field_serializer("quantity", "average_cost")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class TransactionListItem(BaseModel):
    id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    transaction_type: str
    direction: str
    quantity: Decimal
    price: Decimal
    fees: Decimal
    # PLAN-0046 / BP-263: broker-reported cash amount. Required for DIVIDEND
    # rows (units≈0, price≈0, amount=<cash>). NULL for historical rows that
    # pre-date Alembic 0009 and for activity types where the broker omits it.
    amount: Decimal | None = None
    currency: str
    # F-205 (QA iter-2): server-side ticker enrichment so 3rd-party / mobile
    # consumers (and our own frontend before holdings load) can render the
    # ticker without hand-rolling a join. Nullable when the instrument_id
    # isn't yet present in the local instruments cache.
    ticker: str | None = None
    name: str | None = None
    # PLAN-0053 T-D-4-02: asset_class threaded through ListTransactionsUseCase
    # so the frontend can render a coloured badge between Type and Ticker.
    # Nullable for historical rows where the instrument hasn't synced yet
    # (the joined instruments lookup returns None for unknown ids).
    asset_class: str | None = None
    executed_at: datetime
    external_ref: str | None = None
    # P2-E: broker-supplied human-readable description (e.g. "Dividend Payment - AAPL").
    # Not populated for all brokers or activity types. None when omitted by SnapTrade.
    # F-003 (QA Wave G): bound description length at 500 chars — a malicious upstream
    # broker could otherwise push a 100KB+ string that bloats every /transactions
    # response and breaks the React table layout. 500 chars covers all real
    # SnapTrade descriptions we've observed in production.
    description: Annotated[str, StringConstraints(max_length=500)] | None = None
    created_at: datetime

    @field_serializer("quantity", "price", "fees")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal | None) -> str | None:
        # NULL → null in JSON; non-null → 8-dp string for parity with quantity/price.
        return _fmt_decimal(v) if v is not None else None


class InstrumentResponse(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    name: str | None = None
    currency: str | None = None
    asset_class: str | None = None
    entity_id: UUID | None = None


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict = {}


# ── Watchlist schemas ──────────────────────────────────────────────────────────


class WatchlistCreateRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
    )


class WatchlistRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WatchlistResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    name: str
    status: str
    created_at: datetime


class WatchlistMemberCreateRequest(BaseModel):
    entity_id: UUID
    entity_type: str = "company"


class WatchlistMemberResponse(BaseModel):
    """Response from POST /v1/watchlists/{id}/members.

    F-206 (QA iter-2): the response now mirrors the GET-list item shape so
    the frontend's optimistic UI can display the resolved ticker/name (or
    a "resolving…" badge) without a follow-up GET. ``ticker`` / ``name`` /
    ``instrument_id`` are nullable when the local instruments cache had no
    matching entity at add-time (see Alembic 0010 docstring); ``resolution``
    is derived from whether ``ticker`` was populated.
    """

    id: UUID
    watchlist_id: UUID
    entity_id: UUID
    entity_type: str
    added_at: datetime
    ticker: str | None = None
    name: str | None = None
    instrument_id: UUID | None = None
    resolution: str = "resolved"


# ── Watchlist member listing (PLAN-0046 / T-46-2-02) ──────────────────────────


class WatchlistMemberListItem(BaseModel):
    """A member as exposed by ``GET /v1/watchlists/{id}/members``.

    Carries the denormalised ``ticker``/``name``/``instrument_id`` resolved
    at add-time (see Alembic 0010). All three are nullable for historical rows.

    F-010: ``resolution`` is a derived flag — "resolved" when ``ticker`` is
    populated, "pending" when the local instrument cache miss left the row
    with NULL ticker. The frontend renders a small "resolving…" badge for
    pending rows so the user understands why the ticker shows "—".
    """

    entity_id: UUID
    entity_type: str
    ticker: str | None = None
    name: str | None = None
    instrument_id: UUID | None = None
    added_at: datetime
    resolution: str = "resolved"


class WatchlistMemberListResponse(BaseModel):
    """Paginated response for watchlist members."""

    members: list[WatchlistMemberListItem]
    total: int


# ── Alert preference schemas ───────────────────────────────────────────────────


class AlertPreferenceResponse(BaseModel):
    alert_type: str
    enabled: bool
    updated_at: datetime


class AlertPreferenceUpdateRequest(BaseModel):
    enabled: bool


class EntitySuppressionResponse(BaseModel):
    entity_id: UUID
    suppressed_at: datetime


class EntitySuppressionCreateRequest(BaseModel):
    entity_id: UUID


class AlertPreferencesListResponse(BaseModel):
    preferences: list[AlertPreferenceResponse]
    suppressions: list[EntitySuppressionResponse]


# ── Internal API schemas (S10 → S1) ─────────────────────────────────────────


class WatcherInfo(BaseModel):
    """A user watching an entity via a specific watchlist."""

    user_id: UUID
    watchlist_id: UUID
    alert_types: list[str] = []


class WatchersByEntityResponse(BaseModel):
    entity_id: UUID
    watchers: list[WatcherInfo]


class BatchEntityLookupRequest(BaseModel):
    entity_ids: list[UUID]


class BatchEntityLookupResponse(BaseModel):
    results: dict[str, list[WatcherInfo]]


class WatchlistEntitiesResponse(BaseModel):
    watchlist_id: UUID
    entity_ids: list[UUID]


# ── Internal API schemas (S8 → S1) ───────────────────────────────────────────


class HoldingContextItem(BaseModel):
    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None
    quantity: Decimal
    current_weight: float

    @field_serializer("quantity")
    def serialize_quantity(self, v: Decimal) -> str:
        return f"{v:.8f}"


class WatchlistContextItem(BaseModel):
    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None


class PortfolioContextResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    holdings: list[HoldingContextItem]
    watchlist: list[WatchlistContextItem]
    total_positions: int


# ── Brokerage connection schemas (PRD-0022 §6.2) ─────────────────────────────


class InitiateBrokerageConnectionRequest(BaseModel):
    portfolio_id: UUID
    snaptrade_tos_accepted: bool

    @field_validator("snaptrade_tos_accepted")
    @classmethod
    def validate_tos_accepted(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept SnapTrade's End User Terms of Service")
        return v


class InitiateBrokerageConnectionResponse(BaseModel):
    connection_id: UUID
    redirect_uri: str


class BrokerageConnectionResponse(BaseModel):
    connection_id: UUID
    portfolio_id: UUID
    brokerage_name: str | None
    status: str  # pending/active/error/disconnected
    last_synced_at: datetime | None
    created_at: datetime


class ListBrokerageConnectionsResponse(BaseModel):
    items: list[BrokerageConnectionResponse]


class ActivateBrokerageConnectionResponse(BaseModel):
    status: str
    connection_id: UUID


class DisconnectBrokerageConnectionResponse(BaseModel):
    status: str  # "disconnected"


class SyncErrorResponse(BaseModel):
    # raw_transaction intentionally excluded — contains sensitive brokerage data (see PRD §6.4 privacy note)
    # resolved_at excluded: no code path in this plan sets it (reserved for future AcknowledgeSyncError use case)
    id: UUID
    connection_id: UUID
    snaptrade_transaction_id: str
    error_type: str
    error_detail: str | None
    created_at: datetime


class GetSyncErrorsResponse(BaseModel):
    items: list[SyncErrorResponse]


# ── PLAN-0046 Wave 5 — analytics responses ────────────────────────────────────


class ValueHistoryPoint(BaseModel):
    """One point on the equity curve.

    Decimal fields are serialised as 8-dp strings to keep parity with
    every other Decimal in the API. The frontend parses them with
    ``parseFloat`` — string-on-the-wire avoids JS float precision drift
    on values like 1234.56789012.

    F-501 (QA iter-5): ``data_quality`` propagates the snapshot row's
    quality flag to the wire so the equity-curve tooltip can render a
    "Partial prices" caveat when a point's ``value`` was patched up via
    the F-401 stale-price / cost-basis fallback. Defaults to ``"ok"`` so
    legacy rows that pre-date the column (NULL in the DB) still
    serialise cleanly. Forward-compatible: older clients that don't
    read the field are unaffected.
    """

    date: date  # — matches API contract; pydantic resolves the type
    value: Decimal
    cost_basis: Decimal
    cash: Decimal
    # F-501: optional on input (server may pass None for pre-migration rows)
    # but always emitted as a non-empty string on the wire — defaulting NULL
    # to "ok" so the frontend has a single, predictable string-typed field.
    data_quality: str = "ok"

    @field_serializer("value", "cost_basis", "cash")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class ValueHistoryMetadata(BaseModel):
    """Hint block for the equity-curve empty state (F-009, QA iter-2).

    ``last_snapshot_at`` — ISO date of the most recent snapshot **inside the
    returned window**, or ``None`` when the window is empty. The frontend's
    empty-state card uses this to tell the user "your last snapshot was on X"
    (or "none yet") rather than rendering a generic message.

    ``next_scheduled_run_utc`` — full ISO-8601 timestamp of the next 21:30 UTC
    snapshot wake-up. Lets the frontend render a sub-line "Next snapshot
    scheduled for 2026-04-29 21:30 UTC" so the user knows when to expect new
    data instead of guessing the worker is broken.

    Both fields are optional in the wire shape so older clients that don't
    yet read them keep working.
    """

    last_snapshot_at: str | None = None
    next_scheduled_run_utc: str | None = None


class ValueHistoryResponse(BaseModel):
    """``GET /v1/portfolios/{id}/value-history`` response."""

    points: list[ValueHistoryPoint]
    # F-009: empty-state hint metadata. Always populated server-side; clients
    # may safely ignore it if they don't render the empty-state caption.
    metadata: ValueHistoryMetadata = ValueHistoryMetadata()


class ExposureResponse(BaseModel):
    """``GET /v1/portfolios/{id}/exposure`` response.

    ``gross_exposure_pct``/``net_exposure_pct`` are FRACTIONS in [0, 1+]
    (not percent-formatted) to keep parity with every other "_pct"
    field in the codebase. The frontend multiplies by 100 for display.
    ``leverage`` is a multiplier (1.0 = no leverage, 2.0 = 2x).

    F-016: ``prices_stale`` flips True when one or more holdings fell
    back to cost basis because no live quote was available. The frontend
    renders a yellow "Prices stale" badge above the gross-exposure number
    so the user understands the figure may not reflect today's market.
    ``prices_as_of`` is reserved for v2 (see ExposureResult docstring).

    ``buying_power`` (2026-06-10, gap #5): v1 semantics — equals ``cash``
    because margin is not modelled. Explicit field so the frontend renders
    a server-stated value instead of inferring it. Forward-compatible add.
    """

    invested: Decimal
    cash: Decimal
    gross_exposure_pct: Decimal
    net_exposure_pct: Decimal
    leverage: Decimal
    prices_stale: bool = False
    prices_as_of: datetime | None = None
    # v1: always equals cash (no margin). Defaulted for wire compatibility.
    buying_power: Decimal = Decimal(0)

    @field_serializer("invested", "cash", "gross_exposure_pct", "net_exposure_pct", "leverage", "buying_power")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)


# ── Flow-adjusted TWR (2026-06-10 frontend-enhancement sprint, gap #3) ────────


class TwrPointResponse(BaseModel):
    """One day on the TWR curve.

    ``twr_cum_pct`` — cumulative time-weighted return since the first
    snapshot in the window, in percent (first point is always 0.0).
    ``nav`` — the raw daily snapshot value, serialised as an 8-dp string
    to match every other Decimal in the API.
    """

    date: date
    twr_cum_pct: float
    nav: Decimal

    @field_serializer("nav")
    def serialize_nav(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class TwrResponse(BaseModel):
    """``GET /v1/portfolios/{id}/twr`` response.

    Daily time-weighted return series, geometrically linked between
    external cash flows (see ``ComputeTwrUseCase`` for the formula and
    the flow-classification rules). ``flow_days`` counts sub-periods that
    had a non-zero external flow — a sanity-check signal for the caller.

    BP-665 (additive): ``flow_dates`` lists the snapshot dates of those
    flow-adjusted sub-periods, aligned to ``points[].date`` (a flow on a
    non-snapshot day reports the snapshot date it folded into), so the
    frontend's flow-artifact detector can rely on ground truth instead
    of NAV-jump heuristics. ``len(flow_dates) == flow_days``.
    """

    portfolio_id: UUID
    from_date: date
    to_date: date
    points: list[TwrPointResponse]
    flow_days: int
    flow_dates: list[date] = []


# ── PLAN-0051 Wave A — Realised P&L (T-A-1-04) ────────────────────────────────


class RealizedPnLBreakdownItem(BaseModel):
    """Per-instrument totals row inside the realised-P&L response.

    ``ticker``/``name`` come from the local instruments cache. They stay
    ``None`` for instruments not yet mirrored locally; the frontend renders
    "—" in that case (mirrors the holdings list behaviour).
    """

    instrument_id: UUID
    ticker: str | None = None
    name: str | None = None
    realized: Decimal

    @field_serializer("realized")
    def serialize_realized(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class RealizedPnLResponse(BaseModel):
    """``GET /v1/portfolios/{id}/realized-pnl`` response.

    ``total_realized = realized_long_term + realized_short_term`` always
    holds (computed server-side). ``count`` is the number of SELL
    transactions that landed inside the date window, NOT the number of
    chunks matched against open lots.

    Decimals are 8-dp strings on the wire to match the rest of the API.
    """

    total_realized: Decimal
    realized_long_term: Decimal
    realized_short_term: Decimal
    count: int
    breakdown_by_instrument: list[RealizedPnLBreakdownItem]
    currency: str
    from_date: date
    to_date: date

    @field_serializer("total_realized", "realized_long_term", "realized_short_term")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)


# ── PLAN-0088 Wave E — Holdings redesign ──────────────────────────────────────


class HoldingLotItem(BaseModel):
    """One open FIFO lot for the holding-lots drilldown (E-2).

    All Decimal fields serialise as 8-dp strings to match every other
    Decimal in the API. ``unrealised_pnl`` is nullable on the wire so the
    frontend renders "—" cleanly when the gateway couldn't supply a price.
    """

    open_date: date
    qty: Decimal
    cost_per_share: Decimal
    days_held: int
    is_long_term: bool
    unrealised_pnl: Decimal | None = None

    @field_serializer("qty", "cost_per_share")
    def _decimals(self, v: Decimal) -> str:
        return _fmt_decimal(v)

    @field_serializer("unrealised_pnl")
    def _decimal_or_none(self, v: Decimal | None) -> str | None:
        # WHY explicit None handling: field_serializer fires for None too in
        # Pydantic v2; without the guard ``f"{None:.8f}"`` would crash.
        return _fmt_decimal(v) if v is not None else None


class HoldingLotsResponse(BaseModel):
    """``GET /v1/portfolios/{id}/holdings/{instrument_id}/lots`` response."""

    portfolio_id: UUID
    instrument_id: UUID
    lots: list[HoldingLotItem]
    total_qty: Decimal
    total_cost: Decimal
    long_term_qty: Decimal
    short_term_qty: Decimal
    as_of: datetime  # UTC ISO-8601 — emit naturally via Pydantic

    @field_serializer("total_qty", "total_cost", "long_term_qty", "short_term_qty")
    def _decimals(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class TopPositionItem(BaseModel):
    """One entry in the concentration response's top-N list."""

    instrument_id: UUID
    weight_pct: Decimal  # 0-100 (NOT a fraction)

    @field_serializer("weight_pct")
    def _decimals(self, v: Decimal) -> str:
        return _fmt_decimal(v)


class ConcentrationResponse(BaseModel):
    """``GET /v1/portfolios/{id}/concentration`` response (E-3).

    ``hhi`` is the standard 0-10,000 Herfindahl-Hirschman index (sum of
    squared percent weights). ``label`` is ``"diversified"`` (HHI<1500),
    ``"moderate"`` (1500-2500), or ``"concentrated"`` (≥2500). For empty
    portfolios HHI=0 and label="empty".

    ``top_3_share_pct`` is the sum of the three largest position weights as
    a percent (0-100, matching ``weight_pct`` in ``top_positions``).
    """

    portfolio_id: UUID
    hhi: int
    label: str
    top_3_share_pct: Decimal
    positions_count: int
    top_positions: list[TopPositionItem]
    prices_stale: bool

    @field_serializer("top_3_share_pct")
    def _decimals(self, v: Decimal) -> str:
        return _fmt_decimal(v)
