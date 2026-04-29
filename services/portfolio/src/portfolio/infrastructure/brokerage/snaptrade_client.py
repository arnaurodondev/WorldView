"""SnapTrade SDK adapter — concrete implementation of IBrokerageClient.

Upgraded to snaptrade-python-sdk v11 (breaking API changes from v1.0.1):
- Method names changed: snap_trade_register_user_post → register_snap_trade_user
- Method names changed: snap_trade_login_post → login_snap_trade_user
- Method names changed: authorizations_authorization_id_delete → remove_brokerage_authorization
- Response fields: result.user_id → result.body['userId'], result.redirect_uri → result.body['redirectURI']
- Activities endpoint deprecated for customers after 2026-04-25:
  get_activities (HTTP 410) → list_user_accounts + get_account_activities per account

Security invariants (PRD-0022 F-19, F-20):
- ``snaptrade_user_secret`` is NEVER passed to structlog.
- Raw API responses are NEVER logged (may contain account balance/details).
- All SDK exceptions are caught and re-raised as ``BrokerageApiError`` to
  prevent credential leakage in tracebacks.

Performance note (BP-025):
- The snaptrade-python-sdk is synchronous.  Every SDK call is dispatched via
  ``asyncio.get_event_loop().run_in_executor(None, ...)`` so the FastAPI event
  loop is never blocked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog

from portfolio.application.ports.brokerage_client import (
    SnapTradeActivity,
    SnapTradePosition,
    SnapTradeUser,
)
from portfolio.domain.errors import BrokerageApiError

logger = structlog.get_logger(__name__)


def _parse_optional_decimal(value: Any) -> Decimal | None:
    """Coerce a SnapTrade scalar to ``Decimal`` or return ``None`` if absent.

    SnapTrade's v11 DictSchema returns either Python primitives (int/float/str)
    or wrapper objects with ``.value`` semantics. We normalise via ``str()`` to
    avoid float→Decimal precision drift. Empty string is treated as missing.

    PLAN-0046 / BP-263: used for ``amount`` and ``fee`` in ``UniversalActivity``;
    both are independently optional.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (ArithmeticError, ValueError):
        # Defensive: if SnapTrade ever returns a non-numeric string we skip it
        # rather than crash the whole sync cycle. Log via structlog at the call
        # site if desired — here we just degrade gracefully to None.
        return None


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
    """Infrastructure adapter wrapping the snaptrade-python-sdk v11.

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
        from snaptrade_client.apis.tags.account_information_api import (
            AccountInformationApi,  # type: ignore[import-untyped]
        )
        from snaptrade_client.apis.tags.authentication_api import AuthenticationApi  # type: ignore[import-untyped]
        from snaptrade_client.apis.tags.connections_api import ConnectionsApi  # type: ignore[import-untyped]
        from snaptrade_client.apis.tags.transactions_and_reporting_api import (
            TransactionsAndReportingApi,  # type: ignore[import-untyped]
        )

        _config = Configuration(client_id=client_id, consumer_key=consumer_key)
        _api_client = ApiClient(_config)
        self._authentication = AuthenticationApi(_api_client)
        self._connections = ConnectionsApi(_api_client)
        self._account_info = AccountInformationApi(_api_client)
        self._transactions = TransactionsAndReportingApi(_api_client)

    # ── IBrokerageClient protocol methods ────────────────────────────────────

    async def register_user(self, user_id_hint: str) -> SnapTradeUser:
        """Register a new SnapTrade user; returns credentials.

        NEVER log the returned ``user_secret``.

        v11 change: method is now register_snap_trade_user(user_id=...).
        Response fields are result.body['userId'] / result.body['userSecret'].
        """
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._authentication.register_snap_trade_user(
                    user_id=user_id_hint,
                ),
            )
        except Exception as exc:
            # Detect "user already registered" (HTTP 409) — caller should handle
            exc_str = str(exc).lower()
            if "409" in exc_str or "already" in exc_str or "exists" in exc_str:
                logger.warning(
                    "snaptrade_user_already_registered",
                    user_id_hint=user_id_hint,
                    error=type(exc).__name__,
                )
                raise BrokerageApiError(
                    "SnapTrade user already registered",
                    details={"user_id_hint": user_id_hint, "reason": "already_exists"},
                ) from exc
            logger.warning("snaptrade_register_user_failed", user_id_hint=user_id_hint, error=type(exc).__name__)
            raise BrokerageApiError(
                f"SnapTrade register_user failed: {type(exc).__name__}",
                details={"user_id_hint": user_id_hint},
            ) from exc

        # v11: result.body is a DictSchema — access fields via dict syntax
        body = result.body
        return SnapTradeUser(
            snaptrade_user_id=str(body["userId"]),
            snaptrade_user_secret=str(body["userSecret"]),
            # userSecret is NOT logged — only passed back to the use case
        )

    async def delete_user(self, user_id_hint: str) -> None:
        """Delete a SnapTrade user — only called when credentials are lost after DB wipe."""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._authentication.delete_snap_trade_user(user_id=user_id_hint),
            )
        except Exception as exc:
            logger.warning("snaptrade_delete_user_failed", user_id_hint=user_id_hint, error=type(exc).__name__)
            raise BrokerageApiError(
                f"SnapTrade delete_user failed: {type(exc).__name__}",
                details={"user_id_hint": user_id_hint},
            ) from exc

    async def generate_portal_url(self, user: SnapTradeUser, redirect_uri: str) -> str:
        """Generate a Connection Portal URL.

        ``connectionType="read"`` is always hardcoded (PRD-0022 F-22).
        The caller cannot override this value.

        v11 change: method is now login_snap_trade_user(user_id, user_secret, ...).
        Response field is result.body['redirectURI'] (was result.redirect_uri).
        """
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._authentication.login_snap_trade_user(
                    user_id=user.snaptrade_user_id,
                    user_secret=user.snaptrade_user_secret,  # passed to SDK but NEVER logged
                    connection_type="read",  # F-22: HARDCODED — not a parameter
                    custom_redirect=redirect_uri,
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

        # v11: result.body['redirectURI'] (was result.redirect_uri in v1)
        return str(result.body["redirectURI"])

    async def revoke_authorization(self, user: SnapTradeUser, authorization_id: str) -> None:
        """Revoke a SnapTrade brokerage authorization.

        v11 change: method is now remove_brokerage_authorization(...).
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._connections.remove_brokerage_authorization(
                    authorization_id=authorization_id,
                    user_id=user.snaptrade_user_id,
                    user_secret=user.snaptrade_user_secret,  # passed to SDK but NEVER logged
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

        v11 change: get_activities returns HTTP 410 for customers registered
        after 2026-04-25. We first try the legacy endpoint; on 410 or error
        we fall back to per-account activities via list_user_accounts +
        get_account_activities.
        """
        try:
            return await self._get_activities_legacy(user, start, end)
        except BrokerageApiError:
            # Any failure from the legacy endpoint → fall back to per-account.
            # WHY always fall back: the SDK raises ApiException for both 410 Gone
            # (endpoint deprecated) and auth/permission errors; the exception
            # string does not reliably include "410" or "Gone". Per-account is
            # the correct v11 path for all new users (registered after 2026-04-25).
            logger.info(
                "snaptrade_activities_legacy_gone_using_per_account",
                snaptrade_user_id=user.snaptrade_user_id,
            )
            return await self._get_activities_per_account(user, start, end)

    async def _get_activities_legacy(
        self,
        user: SnapTradeUser,
        start: date,
        end: date,
    ) -> list[SnapTradeActivity]:
        """Try the legacy (deprecated) get_activities endpoint."""
        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._transactions.get_activities(
                    user_id=user.snaptrade_user_id,
                    user_secret=user.snaptrade_user_secret,  # NEVER logged
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

        return self._parse_activity_list(results.body if results else [])

    async def _get_activities_per_account(
        self,
        user: SnapTradeUser,
        start: date,
        end: date,
    ) -> list[SnapTradeActivity]:
        """Fetch activities per account (replacement for deprecated endpoint)."""
        # Step 1: list all accounts for this user
        try:
            accounts_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._account_info.list_user_accounts(
                    user_id=user.snaptrade_user_id,
                    user_secret=user.snaptrade_user_secret,  # NEVER logged
                ),
            )
        except Exception as exc:
            logger.warning(
                "snaptrade_list_accounts_failed",
                snaptrade_user_id=user.snaptrade_user_id,
                error=type(exc).__name__,
            )
            raise BrokerageApiError(
                f"SnapTrade list_user_accounts failed: {type(exc).__name__}",
                details={"snaptrade_user_id": user.snaptrade_user_id},
            ) from exc

        accounts = accounts_result.body if accounts_result else []
        all_activities: list[SnapTradeActivity] = []

        # Step 2: fetch activities per account and combine
        for account in accounts:
            account_id = str(account.get("id", ""))
            if not account_id:
                continue
            try:
                act_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda aid=account_id: self._account_info.get_account_activities(  # type: ignore[misc]
                        account_id=aid,
                        user_id=user.snaptrade_user_id,
                        user_secret=user.snaptrade_user_secret,  # NEVER logged
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                    ),
                )
                all_activities.extend(self._parse_activity_list(act_result.body if act_result else []))
            except Exception as exc:
                # Log and continue — one failed account shouldn't block others
                logger.warning(
                    "snaptrade_get_account_activities_failed",
                    snaptrade_user_id=user.snaptrade_user_id,
                    account_id=account_id,
                    error=type(exc).__name__,
                )

        return all_activities

    def _parse_activity_list(self, items: Any) -> list[SnapTradeActivity]:
        """Parse a list of SnapTrade activity items into SnapTradeActivity objects."""
        activities: list[SnapTradeActivity] = []
        if not items:
            return activities

        for item in items:  # type: ignore[union-attr]
            # v11 DictSchema — access fields via dict-style .get()
            symbol_str = ""
            symbol = item.get("symbol") if hasattr(item, "get") else getattr(item, "symbol", None)
            if symbol is not None:
                inner = symbol.get("symbol") if hasattr(symbol, "get") else getattr(symbol, "symbol", None)
                symbol_str = str(inner or "")

            currency_str = ""
            currency = item.get("currency") if hasattr(item, "get") else getattr(item, "currency", None)
            if currency is not None:
                code = currency.get("code") if hasattr(currency, "get") else getattr(currency, "code", None)
                currency_str = str(code or "")

            item_id = item.get("id") if hasattr(item, "get") else getattr(item, "id", None)
            item_type = item.get("type") if hasattr(item, "get") else getattr(item, "type", None)
            item_units = item.get("units") if hasattr(item, "get") else getattr(item, "units", None)
            item_price = item.get("price") if hasattr(item, "get") else getattr(item, "price", None)
            item_trade_date = item.get("trade_date") if hasattr(item, "get") else getattr(item, "trade_date", None)
            item_institution = item.get("institution") if hasattr(item, "get") else getattr(item, "institution", None)
            # ── BP-263 (PLAN-0046 T-46-1-01) ─────────────────────────────────
            # SnapTrade's UniversalActivity carries dividend cash in ``amount``
            # and trade commissions in ``fee``. The pre-PLAN-0046 adapter only
            # read units/price and silently dropped both fields, which made
            # every DIVIDEND row land as $0 in the UI (units≈0, price≈0). We
            # now capture both end-to-end and persist them on the Transaction
            # entity (``amount`` column added in Alembic 0009).
            item_amount = item.get("amount") if hasattr(item, "get") else getattr(item, "amount", None)
            item_fee = item.get("fee") if hasattr(item, "get") else getattr(item, "fee", None)

            # ── PLAN-0051 / T-A-1-06 — F-P-010 ──────────────────────────────
            # When the broker tags a row as DIVIDEND but ships an empty /
            # zero / negative ``amount`` we lose all dividend income for that
            # payout (the UI renders "$0.00" because there is nothing to
            # display). Surface this as a structured warning BEFORE we
            # persist the activity — we deliberately don't drop the row
            # because (a) it might still carry useful metadata for the
            # transactions table and (b) silently dropping rows is exactly
            # the bug class we want to detect, not introduce. The warning
            # gives operators / log-search a stable signal to triage
            # missing-amount payouts.
            parsed_amount = _parse_optional_decimal(item_amount)
            normalised_type = str(item_type or "").upper()
            if normalised_type in ("DIVIDEND", "DIV") and (parsed_amount is None or parsed_amount <= 0):
                logger.warning(
                    "snaptrade_dividend_missing_amount",
                    snaptrade_transaction_id=str(item_id or ""),
                    symbol=symbol_str,
                    currency=currency_str,
                    item_amount=item_amount,
                )

            activities.append(
                SnapTradeActivity(
                    snaptrade_transaction_id=str(item_id or ""),
                    activity_type=str(item_type or ""),
                    symbol=symbol_str,
                    quantity=Decimal(str(item_units or 0)),
                    price=Decimal(str(item_price or 0)),
                    currency=currency_str,
                    executed_at=_parse_trade_date(str(item_trade_date) if item_trade_date else None),
                    brokerage_name=str(item_institution) if item_institution else None,
                    amount=parsed_amount,
                    fee=_parse_optional_decimal(item_fee),
                ),
            )

        return activities

    # ── Position snapshot (PLAN-0046 T-46-1-02 / BP-264) ─────────────────────

    async def list_account_ids(self, user: SnapTradeUser) -> list[str]:
        """List SnapTrade account UUIDs for this user.

        Mirrors the start of ``_get_activities_per_account`` but exposed as a
        first-class operation so the snapshot path can iterate accounts without
        round-tripping through the activity feed.
        """
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._account_info.list_user_accounts(
                    user_id=user.snaptrade_user_id,
                    user_secret=user.snaptrade_user_secret,  # NEVER logged
                ),
            )
        except Exception as exc:
            logger.warning(
                "snaptrade_list_accounts_failed",
                snaptrade_user_id=user.snaptrade_user_id,
                error=type(exc).__name__,
            )
            raise BrokerageApiError(
                f"SnapTrade list_user_accounts failed: {type(exc).__name__}",
                details={"snaptrade_user_id": user.snaptrade_user_id},
            ) from exc

        accounts = result.body if result else []
        ids: list[str] = []
        for account in accounts:
            account_id = str(account.get("id", "")) if hasattr(account, "get") else str(getattr(account, "id", ""))
            if account_id:
                ids.append(account_id)
        return ids

    async def get_account_positions(
        self,
        user: SnapTradeUser,
        account_id: str,
    ) -> list[SnapTradePosition]:
        """Return current positions for a single SnapTrade account.

        Calls ``account_information.get_user_account_positions``. The response is
        a list of position objects, each carrying a ``symbol`` envelope and a
        ``units`` quantity. We normalise this to ``SnapTradePosition`` VOs.

        Skip rules:
        - Missing/empty symbol → skip (cannot resolve to an instrument).
        - Zero quantity → INCLUDE (a closed position; the upsert use case will
          delete the matching ``holdings`` row so the UI no longer shows it).
        """
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._account_info.get_user_account_positions(
                    account_id=account_id,
                    user_id=user.snaptrade_user_id,
                    user_secret=user.snaptrade_user_secret,  # NEVER logged
                ),
            )
        except Exception as exc:
            logger.warning(
                "snaptrade_get_account_positions_failed",
                snaptrade_user_id=user.snaptrade_user_id,
                account_id=account_id,
                error=type(exc).__name__,
            )
            raise BrokerageApiError(
                f"SnapTrade get_account_positions failed: {type(exc).__name__}",
                details={"account_id": account_id},
            ) from exc

        items = result.body if result else []
        positions: list[SnapTradePosition] = []
        if not items:
            return positions

        for item in items:  # type: ignore[union-attr]
            # SnapTrade nests the ticker under symbol.symbol (the inner symbol is the
            # universal-symbol object). Mirror the parsing logic from _parse_activity_list.
            symbol_envelope = item.get("symbol") if hasattr(item, "get") else getattr(item, "symbol", None)
            symbol_str = ""
            currency_str = ""
            if symbol_envelope is not None:
                # The position's symbol envelope nests the universal symbol one level deeper:
                # position.symbol -> { symbol: { symbol: "AAPL", currency: { code: "USD" } } }
                inner = (
                    symbol_envelope.get("symbol")
                    if hasattr(symbol_envelope, "get")
                    else getattr(symbol_envelope, "symbol", None)
                )
                if inner is not None:
                    raw_sym = inner.get("symbol") if hasattr(inner, "get") else getattr(inner, "symbol", None)
                    symbol_str = str(raw_sym or "")
                    currency = inner.get("currency") if hasattr(inner, "get") else getattr(inner, "currency", None)
                    if currency is not None:
                        code = currency.get("code") if hasattr(currency, "get") else getattr(currency, "code", None)
                        currency_str = str(code or "")

            if not symbol_str:
                # No usable ticker — cannot resolve the instrument so skip.
                continue

            units_raw = item.get("units") if hasattr(item, "get") else getattr(item, "units", None)
            avg_raw = (
                item.get("average_purchase_price")
                if hasattr(item, "get")
                else getattr(item, "average_purchase_price", None)
            )
            quantity = _parse_optional_decimal(units_raw) or Decimal(0)
            avg_price = _parse_optional_decimal(avg_raw)

            positions.append(
                SnapTradePosition(
                    account_id=account_id,
                    symbol=symbol_str,
                    quantity=quantity,
                    average_purchase_price=avg_price,
                    currency=currency_str,
                ),
            )

        return positions
