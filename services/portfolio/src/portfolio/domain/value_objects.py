"""Immutable value objects for the Portfolio domain."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from portfolio.domain.enums import AuthAuditEventType, TransactionType

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
        return cls(amount=Decimal(0), currency=currency)

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
        return self.amount == Decimal(0)

    def is_positive(self) -> bool:
        return self.amount > Decimal(0)

    def is_negative(self) -> bool:
        return self.amount < Decimal(0)


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
        return cls(value=Decimal(0))

    def __add__(self, other: Quantity) -> Quantity:
        return Quantity(value=self.value + other.value)

    def __sub__(self, other: Quantity) -> Quantity:
        return Quantity(value=self.value - other.value)

    def __mul__(self, factor: Decimal | int) -> Quantity:
        return Quantity(value=self.value * Decimal(factor))

    def __neg__(self) -> Quantity:
        return Quantity(value=-self.value)

    def is_zero(self) -> bool:
        return self.value == Decimal(0)

    def is_positive(self) -> bool:
        return self.value > Decimal(0)

    def is_negative(self) -> bool:
        return self.value < Decimal(0)


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


@dataclass(frozen=True)
class TransactionFilter:
    """Server-side filter value object for ListTransactions / ExportTransactions.

    PLAN-0114 / T-W2-03: all fields are optional. Absent fields are not
    applied as WHERE predicates by the repository.

    Validation (``__post_init__``):
    - ``to_date >= from_date`` when both are present.
    - Range <= 5 years (1826 days) to prevent runaway queries.
    """

    from_date: date | None = None
    to_date: date | None = None
    transaction_types: list[TransactionType] = field(default_factory=list)
    ticker: str | None = None
    limit: int = 50
    offset: int = 0
    # Non-configurable constant: 5-year cap in days.
    _MAX_RANGE_DAYS: int = field(default=1826, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Ticker guard: max 20 chars, alphanumeric + dot/caret/hyphen only.
        # WHY here: even if the API layer validates Query params, the domain VO
        # is the canonical guard — callers that construct TransactionFilter
        # directly (e.g. export use case) benefit from the same constraint.
        if self.ticker is not None:
            if len(self.ticker) > 20:
                raise ValueError(f"ticker must be at most 20 characters, got {len(self.ticker)}")
            # Accept lowercase input: ticker matching is case-insensitive (the
            # repository upper-cases before an ILIKE), so a lowercase filter such
            # as "aapl" is a valid, intended query. We still reject any character
            # outside the ticker alphabet (rejects ILIKE wildcards/injection).
            if not re.fullmatch(r"[A-Za-z0-9.\^-]*", self.ticker):
                raise ValueError(
                    f"ticker '{self.ticker}' contains invalid characters. "
                    "Only letters, digits, '.', '^', and '-' are allowed."
                )
            # Normalize to upper-case so the canonical VO value matches the
            # symbol storage convention (frozen dataclass → use object.__setattr__).
            object.__setattr__(self, "ticker", self.ticker.upper())
        if self.from_date is not None and self.to_date is not None:
            if self.to_date < self.from_date:
                raise ValueError(f"to_date ({self.to_date}) must be >= from_date ({self.from_date})")
            delta = (self.to_date - self.from_date).days
            if delta > self._MAX_RANGE_DAYS:
                raise ValueError(
                    f"Date range {delta} days exceeds the 5-year cap ({self._MAX_RANGE_DAYS} days). "
                    "Split the request into smaller date ranges."
                )
        elif self.from_date is not None:
            # FQ-007: open-ended range (from_date only, no to_date) was bypassing
            # the 5-year cap because the guard above required BOTH dates.  A query
            # with only from_date scans from that date to *now*, which can exceed
            # the cap if from_date is in the distant past.  Validate against today
            # so the cap is enforced regardless of whether to_date is supplied.
            # WHY timedelta(days=_MAX_RANGE_DAYS): mirrors the closed-range check
            # above; "today - from_date <= 5 years" is the equivalent open-ended cap.
            days_from_start = (datetime.now(UTC).date() - self.from_date).days
            if days_from_start > self._MAX_RANGE_DAYS:
                raise ValueError(
                    f"from_date ({self.from_date}) is more than 5 years ago "
                    f"({days_from_start} days). Provide a to_date or use a more "
                    "recent from_date to stay within the 5-year cap."
                )
        elif self.to_date is not None:
            # Open-ended range with only to_date: the lower bound is "the beginning
            # of time" for that portfolio. Cap: to_date must not be more than 5 years
            # in the future (prevents absurd queries like to_date=2099-01-01).
            # WHY: a to_date far in the future combined with no from_date could scan
            # all historical rows plus every future projected row if the schema ever
            # gains forward-looking records.  Bound it symmetrically.
            days_to_end = (self.to_date - datetime.now(UTC).date()).days
            if days_to_end > self._MAX_RANGE_DAYS:
                raise ValueError(
                    f"to_date ({self.to_date}) is more than 5 years in the future "
                    f"({days_to_end} days). Provide a from_date or use a sooner to_date."
                )
