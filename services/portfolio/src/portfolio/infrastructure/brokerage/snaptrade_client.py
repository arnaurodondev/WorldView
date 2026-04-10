"""SnapTrade SDK adapter — concrete implementation of IBrokerageClient.

Security invariants (PRD-0022 F-19, F-20):
- ``snaptrade_user_secret`` is NEVER passed to structlog.
- Raw API responses are NEVER logged (may contain account balance/details).
- All SDK exceptions are caught and re-raised as ``BrokerageApiError`` to
  prevent credential leakage in tracebacks.

Performance note (BP-025):
- The snaptrade-python-sdk is synchronous.  Every SDK call is dispatched via
  ``asyncio.get_event_loop().run_in_executor(None, ...)`` so the FastAPI event
  loop is never blocked.

SDK method mapping (verified against snaptrade-python-sdk==1.0.1):
- register_user      → AuthenticationApi.snap_trade_register_user_post
- generate_portal_url → AuthenticationApi.snap_trade_login_post
- revoke_authorization → ConnectionsApi.authorizations_authorization_id_delete
- get_activities      → TransactionsAndReportingApi.activities_get
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from portfolio.application.ports.brokerage_client import SnapTradeActivity, SnapTradeUser
from portfolio.domain.errors import BrokerageApiError

if TYPE_CHECKING:
    from datetime import date

logger = structlog.get_logger(__name__)


def _parse_trade_date(trade_date: str | None) -> datetime:
    """Parse an ISO date string (YYYY-MM-DD) from SnapTrade into a UTC datetime."""
    if not trade_date:
        return datetime.now(tz=UTC)
    try:
        # trade_date is "YYYY-MM-DD"; treat as UTC midnight
        return datetime.fromisoformat(trade_date).replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(tz=UTC)


class SnapTradeClient:
    """Infrastructure adapter wrapping the snaptrade-python-sdk.

    Implements the ``IBrokerageClient`` Protocol.  SDK objects are constructed
    once at init time; the Configuration holds ``client_id`` and
    ``consumer_key`` for HMAC signing.

    Args:
        client_id: SnapTrade partner client ID (``SNAPTRADE_CLIENT_ID``).
        consumer_key: SnapTrade partner consumer key (``SNAPTRADE_CONSUMER_KEY``).
    """

    def __init__(self, client_id: str, consumer_key: str) -> None:
        # Lazy import — SDK imports are slow; kept inside __init__ so the module
        # can be imported without SDK installed (e.g. during linting in CI).
        from snaptrade_client import ApiClient, Configuration  # type: ignore[import-untyped]
        from snaptrade_client.api.authentication_api import AuthenticationApi  # type: ignore[import-untyped]
        from snaptrade_client.api.connections_api import ConnectionsApi  # type: ignore[import-untyped]
        from snaptrade_client.api.transactions_and_reporting_api import (  # type: ignore[import-untyped]
            TransactionsAndReportingApi,
        )

        _config = Configuration(client_id=client_id, consumer_key=consumer_key)
        _api_client = ApiClient(_config)
        self._authentication = AuthenticationApi(_api_client)
        self._connections = ConnectionsApi(_api_client)
        self._transactions = TransactionsAndReportingApi(_api_client)

    # ── IBrokerageClient protocol methods ────────────────────────────────────

    async def register_user(self, user_id_hint: str) -> SnapTradeUser:
        """Register a new SnapTrade user; returns credentials.

        NEVER log the returned ``user_secret``.
        """
        try:
            from snaptrade_client.models import SnapTradeRegisterUserRequestBody  # type: ignore[import-untyped]

            body = SnapTradeRegisterUserRequestBody(user_id=user_id_hint)
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._authentication.snap_trade_register_user_post(body),
            )
        except Exception as exc:
            logger.warning("snaptrade_register_user_failed", user_id_hint=user_id_hint, error=type(exc).__name__)
            raise BrokerageApiError(
                f"SnapTrade register_user failed: {type(exc).__name__}",
                details={"user_id_hint": user_id_hint},
            ) from exc

        return SnapTradeUser(
            snaptrade_user_id=result.user_id,
            snaptrade_user_secret=result.user_secret,
            # user_secret is NOT logged — only passed back to the use case
        )

    async def generate_portal_url(self, user: SnapTradeUser, redirect_uri: str) -> str:
        """Generate a Connection Portal URL.

        ``connectionType="read"`` is always hardcoded (PRD-0022 F-22).
        The caller cannot override this value.
        """
        try:
            from snaptrade_client.models import SnapTradeLoginUserRequestBody  # type: ignore[import-untyped]

            body = SnapTradeLoginUserRequestBody(
                connection_type="read",  # F-22: HARDCODED — not a parameter
                custom_redirect=redirect_uri,
            )
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._authentication.snap_trade_login_post(
                    user.snaptrade_user_id,
                    user.snaptrade_user_secret,  # passed to SDK but NEVER logged
                    snap_trade_login_user_request_body=body,
                ),
            )
        except Exception as exc:
            logger.warning(
                "snaptrade_generate_portal_url_failed",
                snaptrade_user_id=user.snaptrade_user_id,
                error=type(exc).__name__,
            )
            raise BrokerageApiError(
                f"SnapTrade generate_portal_url failed: {type(exc).__name__}",
                details={"snaptrade_user_id": user.snaptrade_user_id},
            ) from exc

        return str(result.redirect_uri)

    async def revoke_authorization(self, user: SnapTradeUser, authorization_id: str) -> None:
        """Revoke a SnapTrade brokerage authorization."""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._connections.authorizations_authorization_id_delete(
                    authorization_id,
                    user.snaptrade_user_id,
                    user.snaptrade_user_secret,  # passed to SDK but NEVER logged
                ),
            )
        except Exception as exc:
            logger.warning(
                "snaptrade_revoke_authorization_failed",
                snaptrade_user_id=user.snaptrade_user_id,
                authorization_id=authorization_id,
                error=type(exc).__name__,
            )
            raise BrokerageApiError(
                f"SnapTrade revoke_authorization failed: {type(exc).__name__}",
                details={"authorization_id": authorization_id},
            ) from exc

    async def get_activities(
        self,
        user: SnapTradeUser,
        start: date,
        end: date,
    ) -> list[SnapTradeActivity]:
        """Fetch brokerage activities for a date range.

        Raw API responses are NEVER logged — they may contain account details.
        """
        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._transactions.activities_get(
                    user.snaptrade_user_id,
                    user.snaptrade_user_secret,  # passed to SDK but NEVER logged
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                ),
            )
        except Exception as exc:
            logger.warning(
                "snaptrade_get_activities_failed",
                snaptrade_user_id=user.snaptrade_user_id,
                error=type(exc).__name__,
            )
            raise BrokerageApiError(
                f"SnapTrade get_activities failed: {type(exc).__name__}",
                details={"snaptrade_user_id": user.snaptrade_user_id},
            ) from exc

        activities: list[SnapTradeActivity] = []
        for item in results or []:
            symbol_str = ""
            if item.symbol is not None:
                symbol_str = str(item.symbol.symbol or "")

            currency_str = ""
            if item.currency is not None:
                currency_str = str(item.currency.code or "")

            activities.append(
                SnapTradeActivity(
                    snaptrade_transaction_id=str(item.id or ""),
                    activity_type=str(item.type or ""),
                    symbol=symbol_str,
                    quantity=Decimal(str(item.units or 0)),
                    price=Decimal(str(item.price or 0)),
                    currency=currency_str,
                    executed_at=_parse_trade_date(item.trade_date),
                    brokerage_name=str(item.institution) if item.institution else None,
                )
            )

        return activities
