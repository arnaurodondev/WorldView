"""Pydantic request/response schemas for the Portfolio API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_serializer, field_validator


def _fmt_decimal(v: Decimal) -> str:
    """Serialize Decimal to 8-decimal-place string (matches DB Numeric(18,8))."""
    return f"{v:.8f}"


def _validate_currency(v: str) -> str:
    if not (len(v) == 3 and v.isupper() and v.isalpha()):
        raise ValueError(f"Currency must be a 3-letter uppercase code, got: {v!r}")
    return v


class TenantCreateRequest(BaseModel):
    name: str


class TenantResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime


class UserCreateRequest(BaseModel):
    tenant_id: UUID
    email: str


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    status: str
    created_at: datetime


class PortfolioCreateRequest(BaseModel):
    name: str
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
    name: str


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


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict = {}
