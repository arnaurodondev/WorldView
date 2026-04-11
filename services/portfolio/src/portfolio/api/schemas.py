"""Pydantic request/response schemas for the Portfolio API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_serializer, field_validator

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
    created_at: datetime


class PortfolioRenameRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class RecordTransactionRequest(BaseModel):
    portfolio_id: UUID
    instrument_id: UUID
    transaction_type: str
    direction: str
    quantity: Decimal
    price: Decimal
    fees: Decimal = Decimal("0")
    currency: str
    executed_at: datetime
    external_ref: str | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        return _validate_currency(v)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("quantity must be positive")
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
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
    currency: str
    executed_at: datetime
    external_ref: str | None = None
    created_at: datetime

    @field_serializer("quantity", "price", "fees")
    def serialize_decimal(self, v: Decimal) -> str:
        return _fmt_decimal(v)


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
    id: UUID
    watchlist_id: UUID
    entity_id: UUID
    entity_type: str
    added_at: datetime


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
