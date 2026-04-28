"""Domain enumerations for the Portfolio service."""

from __future__ import annotations

from enum import StrEnum

from messaging.enums import OutboxStatus as OutboxStatus  # — canonical re-export


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


class PortfolioStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class PortfolioKind(StrEnum):
    """Discriminator for portfolio purpose / data source.

    PLAN-0046 Wave 3 / T-46-3-01.

    - ``MANUAL``    : user-created via ``POST /v1/portfolios``; transactions
                      are recorded manually by the user.
    - ``BROKERAGE`` : created during a SnapTrade brokerage connection flow;
                      holdings are derived from broker snapshots.
    - ``ROOT``      : auto-provisioned per user (one only — enforced by a
                      partial unique index). Aggregates holdings/transactions
                      across all the user's other portfolios. Cannot be
                      archived, renamed away from "All Accounts" by users,
                      or written to via ``POST /v1/transactions``.
    """

    MANUAL = "manual"
    BROKERAGE = "brokerage"
    ROOT = "root"


class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    FEE = "FEE"


class TransactionDirection(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class IdempotencyState(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WatchlistStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class AlertType(StrEnum):
    SIGNAL = "signal"
    CONTRADICTION = "contradiction"
    CONFIDENCE_DROP = "confidence_drop"
    NEW_EVENT = "new_event"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class SyncErrorType(StrEnum):
    UNKNOWN_INSTRUMENT = "unknown_instrument"
    UNSUPPORTED_TYPE = "unsupported_type"
    API_ERROR = "api_error"
    VALIDATION_ERROR = "validation_error"


class TenantUserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class AuthAuditEventType(StrEnum):
    USER_CREATED = "user_created"
    ACCOUNT_LINKED = "account_linked"
    LOGIN_PROVISIONED = "login_provisioned"
    PROVISION_CONFLICT_409 = "provision_conflict_409"
