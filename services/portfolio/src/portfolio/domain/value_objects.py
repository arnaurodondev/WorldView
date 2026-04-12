"""Immutable value objects for the Portfolio domain."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.domain.enums import AuthAuditEventType

_PRECISION = Decimal("0.00000001")  # (18,8) scale


@dataclass(frozen=True)
class Money:
    """Monetary amount with currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", self.amount.quantize(_PRECISION, rounding=ROUND_HALF_UP))

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(amount=Decimal("0"), currency=currency)

    @classmethod
    def from_string(cls, amount_str: str, currency: str) -> Money:
        return cls(amount=Decimal(amount_str), currency=currency)

    def _check_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        return Money(amount=self.amount * Decimal(factor), currency=self.currency)

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def is_zero(self) -> bool:
        return self.amount == Decimal("0")

    def is_positive(self) -> bool:
        return self.amount > Decimal("0")

    def is_negative(self) -> bool:
        return self.amount < Decimal("0")


@dataclass(frozen=True)
class InstrumentKey:
    """Unique identifier for a financial instrument."""

    symbol: str
    exchange: str

    def full_symbol(self) -> str:
        return f"{self.symbol}:{self.exchange}"


@dataclass(frozen=True)
class Quantity:
    """Signed quantity of an instrument holding."""

    value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", self.value.quantize(_PRECISION, rounding=ROUND_HALF_UP))

    @classmethod
    def zero(cls) -> Quantity:
        return cls(value=Decimal("0"))

    def __add__(self, other: Quantity) -> Quantity:
        return Quantity(value=self.value + other.value)

    def __sub__(self, other: Quantity) -> Quantity:
        return Quantity(value=self.value - other.value)

    def __mul__(self, factor: Decimal | int) -> Quantity:
        return Quantity(value=self.value * Decimal(factor))

    def __neg__(self) -> Quantity:
        return Quantity(value=-self.value)

    def is_zero(self) -> bool:
        return self.value == Decimal("0")

    def is_positive(self) -> bool:
        return self.value > Decimal("0")

    def is_negative(self) -> bool:
        return self.value < Decimal("0")


@dataclass(frozen=True)
class AuthAuditEvent:
    """Immutable record of an authentication or provisioning event.

    Written to ``auth_audit_log`` by ``ProvisionUserUseCase``.
    ``ip_address`` is stored as a truncated SHA-256 hash (16 hex chars)
    to avoid storing raw PII in logs.
    """

    event_type: AuthAuditEventType
    sub: str
    user_id: UUID | None
    email: str | None
    detail: dict[str, str]
    ip_address: str | None = None
