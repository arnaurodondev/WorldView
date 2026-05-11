"""IBrokerageClient port and SnapTrade value objects for the application layer.

This module defines the abstract brokerage client interface (Protocol) and the
value objects that cross the adapter boundary. No infrastructure imports are
allowed here — this is a pure application-layer port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


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
    """Value object representing a single SnapTrade brokerage activity.

    PLAN-0046 / BP-263: ``amount`` and ``fee`` were previously dropped by the
    adapter, causing DIVIDEND rows to render as $0 (units≈0, price≈0). They are
    now captured end-to-end. Both are optional because not every activity type
    populates them.
    """

    snaptrade_transaction_id: str  # SnapTrade's unique ID for this activity
    activity_type: str  # Raw type string from SnapTrade (e.g. "BUY", "SELL", "DIV")
    symbol: str  # Ticker symbol
    quantity: Decimal
    price: Decimal
    currency: str  # ISO-4217 currency code (e.g. "USD")
    executed_at: datetime  # UTC-aware execution timestamp
    brokerage_name: str | None = None  # Human-readable brokerage name if available
    # Broker-reported cash amount. For DIVIDEND this is the cash payment; for
    # BUY/SELL it is approximately quantity*price (broker-rounded) and is
    # informational. NULL when SnapTrade omits the field.
    amount: Decimal | None = None
    # Broker fee charged on the activity (commission, regulatory fees, etc.).
    # Always None for DIVIDEND. None when SnapTrade omits the field.
    fee: Decimal | None = None
    # P2-E: broker-supplied human-readable description (e.g. "Dividend Payment - AAPL").
    # Null when SnapTrade omits the field or the activity type does not carry one.
    description: str | None = None
    # P2-E: the settlement date of the trade (T+1 equities, T+2 legacy).
    # Distinct from ``executed_at`` (trade/execution date). None when omitted.
    settlement_date: date | None = None


@dataclass(frozen=True)
class SnapTradePosition:
    """Value object representing a single current position from SnapTrade.

    Returned by ``IBrokerageClient.get_account_positions``. This is the broker's
    *snapshot* of what the account holds right now and is used to overwrite the
    ``holdings`` table after each sync (PLAN-0046 / BP-264 — never replay
    activities to derive cumulative state).
    """

    account_id: str
    symbol: str  # Ticker symbol
    quantity: Decimal
    average_purchase_price: Decimal | None  # Some brokers omit cost basis
    currency: str  # ISO-4217 currency code (e.g. "USD")


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

        Raises ``BrokerageApiError(reason="already_exists")`` when the user is
        already registered in SnapTrade (HTTP 409). Callers should handle this
        by recovering credentials from the DB (``delete_user`` + re-register if lost).
        """
        ...

    async def delete_user(self, user_id_hint: str) -> None:
        """Delete a SnapTrade user — used to recover from "already_exists" when credentials are lost.

        Called ONLY when ``register_user`` raises ``BrokerageApiError(reason="already_exists")``
        and no stored credentials can be found in the DB (e.g., after a full data wipe).
        After deletion, the caller re-registers the user fresh.
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

    async def list_account_ids(self, user: SnapTradeUser) -> list[str]:
        """Return the list of SnapTrade account UUIDs linked to this user.

        Used by the snapshot path (PLAN-0046 T-46-1-03) to iterate accounts and
        fetch positions. Implementations should swallow per-account errors and
        return whatever they can.
        """
        ...

    async def get_account_positions(
        self,
        user: SnapTradeUser,
        account_id: str,
    ) -> list[SnapTradePosition]:
        """Fetch the broker's current position snapshot for one account.

        PLAN-0046 T-46-1-02 / BP-264: holdings must be derived from this snapshot,
        NOT from cumulative activity replay. Activity feeds can return duplicates
        across endpoint families (legacy vs per-account) and across linked sub
        accounts; the snapshot is the only authoritative source for "what the user
        holds right now".

        Args:
            user: SnapTrade credentials for this Worldview user.
            account_id: SnapTrade account UUID (string).

        Returns:
            A list of ``SnapTradePosition`` objects. May be empty.
        """
        ...

    async def get_account_balance(
        self,
        user: SnapTradeUser,
        account_id: str,
    ) -> dict[str, Any] | None:
        """Return cash/buying-power balance for one brokerage account.

        Args:
            user: SnapTrade credentials for this Worldview user.
            account_id: SnapTrade account UUID (string).

        Returns:
            A dict with ``cash`` (Decimal), ``buying_power`` (Decimal|None),
            and ``currency`` (str) when available, or ``None`` when the broker
            does not expose balance data for this account type.
        """
        ...
