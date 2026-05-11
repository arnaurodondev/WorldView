"""Unit tests for brokerage domain entities and enums (Wave A-1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.enums import ConnectionStatus, SyncErrorType
from portfolio.domain.errors import (
    BrokerageConnectionAlreadyDisconnectedError,
    BrokerageConnectionStateError,
)

pytestmark = pytest.mark.unit

_TOS_ACCEPTED = datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)


def _make_connection(**kwargs: object) -> BrokerageConnection:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "portfolio_id": uuid.uuid4(),
        "snaptrade_user_id": "snap-user-123",
        "snaptrade_user_secret": "super-secret-token",
        "snaptrade_tos_accepted_at": _TOS_ACCEPTED,
    }
    defaults.update(kwargs)
    return BrokerageConnection(**defaults)  # type: ignore[arg-type]


# ── Enum tests ─────────────────────────────────────────────────────────────────


class TestConnectionStatusValues:
    def test_connection_status_values(self) -> None:
        assert ConnectionStatus.PENDING == "pending"
        assert ConnectionStatus.ACTIVE == "active"
        assert ConnectionStatus.ERROR == "error"
        assert ConnectionStatus.DISCONNECTED == "disconnected"

    def test_all_members_present(self) -> None:
        members = {m.value for m in ConnectionStatus}
        assert members == {"pending", "active", "error", "disconnected"}


class TestSyncErrorTypeValues:
    def test_sync_error_type_values(self) -> None:
        assert SyncErrorType.UNKNOWN_INSTRUMENT == "unknown_instrument"
        assert SyncErrorType.UNSUPPORTED_TYPE == "unsupported_type"
        assert SyncErrorType.API_ERROR == "api_error"
        assert SyncErrorType.VALIDATION_ERROR == "validation_error"

    def test_all_members_present(self) -> None:
        members = {m.value for m in SyncErrorType}
        assert members == {"unknown_instrument", "unsupported_type", "api_error", "validation_error"}


# ── BrokerageConnection tests ──────────────────────────────────────────────────


class TestBrokerageConnectionSecretRedaction:
    def test_secret_redacted_in_repr(self) -> None:
        conn = _make_connection(snaptrade_user_secret="my-real-secret")
        representation = repr(conn)
        assert "my-real-secret" not in representation
        assert "***REDACTED***" in representation

    def test_secret_not_in_str(self) -> None:
        conn = _make_connection(snaptrade_user_secret="my-real-secret")
        # dataclass __str__ delegates to __repr__ when overridden
        assert "my-real-secret" not in repr(conn)


class TestBrokerageConnectionActivate:
    def test_activate_valid(self) -> None:
        conn = _make_connection()
        assert conn.status == ConnectionStatus.PENDING
        conn.activate("auth-id-abc")
        assert conn.status == ConnectionStatus.ACTIVE
        assert conn.authorization_id == "auth-id-abc"

    def test_activate_invalid_state_active(self) -> None:
        conn = _make_connection(status=ConnectionStatus.ACTIVE)
        with pytest.raises(BrokerageConnectionStateError):
            conn.activate("auth-id-abc")

    def test_activate_invalid_state_error(self) -> None:
        conn = _make_connection(status=ConnectionStatus.ERROR)
        with pytest.raises(BrokerageConnectionStateError):
            conn.activate("auth-id-abc")

    def test_activate_updates_updated_at(self) -> None:
        conn = _make_connection()
        before = conn.updated_at
        conn.activate("auth-id-abc")
        assert conn.updated_at >= before


class TestBrokerageConnectionDisconnect:
    def test_disconnect_from_active(self) -> None:
        conn = _make_connection(status=ConnectionStatus.ACTIVE)
        conn.disconnect()
        assert conn.status == ConnectionStatus.DISCONNECTED

    def test_disconnect_from_error(self) -> None:
        conn = _make_connection(status=ConnectionStatus.ERROR)
        conn.disconnect()
        assert conn.status == ConnectionStatus.DISCONNECTED

    def test_disconnect_already_disconnected_raises(self) -> None:
        conn = _make_connection(status=ConnectionStatus.DISCONNECTED)
        with pytest.raises(BrokerageConnectionAlreadyDisconnectedError):
            conn.disconnect()


class TestBrokerageConnectionMarkError:
    def test_mark_error(self) -> None:
        conn = _make_connection(status=ConnectionStatus.ACTIVE)
        conn.mark_error()
        assert conn.status == ConnectionStatus.ERROR


# ── BrokerageTransactionSyncError tests ───────────────────────────────────────


class TestBrokerageTransactionSyncError:
    def test_is_frozen(self) -> None:
        err = BrokerageTransactionSyncError(
            connection_id=uuid.uuid4(),
            snaptrade_transaction_id="txn-001",
            error_type=SyncErrorType.UNKNOWN_INSTRUMENT,
        )
        with pytest.raises((AttributeError, TypeError)):
            err.error_type = SyncErrorType.API_ERROR  # type: ignore[misc]

    def test_default_fields_are_none(self) -> None:
        err = BrokerageTransactionSyncError(
            connection_id=uuid.uuid4(),
            snaptrade_transaction_id="txn-002",
            error_type=SyncErrorType.VALIDATION_ERROR,
        )
        assert err.error_detail is None
        assert err.raw_transaction is None

    def test_raw_transaction_stored(self) -> None:
        raw = {"type": "BUY", "symbol": "AAPL"}
        err = BrokerageTransactionSyncError(
            connection_id=uuid.uuid4(),
            snaptrade_transaction_id="txn-003",
            error_type=SyncErrorType.API_ERROR,
            raw_transaction=raw,
        )
        assert err.raw_transaction == raw
