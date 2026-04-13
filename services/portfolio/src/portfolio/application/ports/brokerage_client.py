"""IBrokerageClient port and SnapTrade value objects for the application layer.

This module defines the abstract brokerage client interface (Protocol) and the
value objects that cross the adapter boundary. No infrastructure imports are
allowed here — this is a pure application-layer port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal


@dataclass(frozen=True)
class SnapTradeUser:
    """Value object carrying SnapTrade user credentials.

    The ``snaptrade_user_secret`` must never appear in logs, tracebacks, or
    string representations.  ``__repr__`` is overridden to enforce this.
    """

    snaptrade_user_id: str
    snaptrade_user_secret: str  # NEVER LOG — secret token

    def __repr__(self) -> str:
        return f"SnapTradeUser(snaptrade_user_id={self.snaptrade_user_id!r}, snaptrade_user_secret='***REDACTED***')"


@dataclass(frozen=True)
class SnapTradeActivity:
    """Value object representing a single SnapTrade brokerage activity."""

    snaptrade_transaction_id: str  # SnapTrade's unique ID for this activity
    activity_type: str  # Raw type string from SnapTrade (e.g. "BUY", "SELL", "DIV")
    symbol: str  # Ticker symbol
    quantity: Decimal
    price: Decimal
    currency: str  # ISO-4217 currency code (e.g. "USD")
    executed_at: datetime  # UTC-aware execution timestamp
    brokerage_name: str | None = None  # Human-readable brokerage name if available


@runtime_checkable
class IBrokerageClient(Protocol):
    """Port interface for brokerage connectivity.

    All methods are async.  Concrete implementations wrap a synchronous SDK
    using ``asyncio.run_in_executor`` (BP-025).  Tests inject
    ``FakeBrokerageClient`` instead.

    Design notes:
    - ``connectionType="read"`` is always hardcoded in ``generate_portal_url``
      (PRD-0022 F-22) — callers cannot override it.
    - Implementations must never log ``snaptrade_user_secret``.
    - Any SDK exception must be re-raised as ``BrokerageApiError``.
    """

    async def register_user(self, user_id_hint: str) -> SnapTradeUser:
        """Register a new SnapTrade user and return the user credentials.

        Args:
            user_id_hint: An opaque string identifier (typically the Worldview
                user ID string) used as the SnapTrade userId.

        Returns:
            A ``SnapTradeUser`` with both ``snaptrade_user_id`` and
            ``snaptrade_user_secret`` populated.
        """
        ...

    async def generate_portal_url(self, user: SnapTradeUser, redirect_uri: str) -> str:
        """Generate a SnapTrade Connection Portal redirect URL.

        ``connectionType`` is hardcoded to ``"read"`` — callers cannot supply
        a different value (PRD-0022 F-22).

        Args:
            user: SnapTrade credentials for this Worldview user.
            redirect_uri: The URI SnapTrade will redirect back to after the
                user connects their brokerage account.

        Returns:
            The ``redirectURI`` string to forward to the frontend.
        """
        ...

    async def revoke_authorization(self, user: SnapTradeUser, authorization_id: str) -> None:
        """Revoke a brokerage authorization in SnapTrade.

        Args:
            user: SnapTrade credentials for this Worldview user.
            authorization_id: The SnapTrade authorization ID to revoke.
        """
        ...

    async def get_activities(
        self,
        user: SnapTradeUser,
        start: date,
        end: date,
    ) -> list[SnapTradeActivity]:
        """Fetch brokerage transaction activities for a date range.

        Args:
            user: SnapTrade credentials for this Worldview user.
            start: Inclusive start date (UTC).
            end: Inclusive end date (UTC).

        Returns:
            A list of ``SnapTradeActivity`` objects.  May be empty.
        """
        ...
