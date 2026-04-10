"""Unit tests for IBrokerageClient port value objects and FakeBrokerageClient (Wave B-1)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from portfolio.application.ports.brokerage_client import IBrokerageClient, SnapTradeActivity, SnapTradeUser
from portfolio.domain.errors import BrokerageApiError

from tests.unit.fakes import FakeBrokerageClient

pytestmark = pytest.mark.unit


# ── SnapTradeUser ──────────────────────────────────────────────────────────────


class TestSnapTradeUserSecretRedaction:
    def test_secret_not_in_repr(self) -> None:
        secret = "my-real-secret"  # noqa: S105
        user = SnapTradeUser(snaptrade_user_id="user-1", snaptrade_user_secret=secret)
        assert secret not in repr(user)
        assert "***REDACTED***" in repr(user)

    def test_user_id_visible_in_repr(self) -> None:
        user = SnapTradeUser(snaptrade_user_id="user-1", snaptrade_user_secret="secret")
        assert "user-1" in repr(user)

    def test_frozen(self) -> None:
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        with pytest.raises((AttributeError, TypeError)):
            user.snaptrade_user_secret = "new-secret"  # type: ignore[misc]  # noqa: S105


# ── SnapTradeActivity ──────────────────────────────────────────────────────────


class TestSnapTradeActivity:
    def test_frozen(self) -> None:
        act = SnapTradeActivity(
            snaptrade_transaction_id="txn-1",
            activity_type="BUY",
            symbol="AAPL",
            quantity=Decimal("10"),
            price=Decimal("150.00"),
            currency="USD",
            executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises((AttributeError, TypeError)):
            act.symbol = "TSLA"  # type: ignore[misc]

    def test_brokerage_name_defaults_to_none(self) -> None:
        act = SnapTradeActivity(
            snaptrade_transaction_id="txn-2",
            activity_type="SELL",
            symbol="GOOG",
            quantity=Decimal("5"),
            price=Decimal("100"),
            currency="USD",
            executed_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert act.brokerage_name is None


# ── IBrokerageClient Protocol ──────────────────────────────────────────────────


class TestIBrokerageClientProtocol:
    def test_fake_satisfies_protocol(self) -> None:
        fake = FakeBrokerageClient()
        assert isinstance(fake, IBrokerageClient)


# ── FakeBrokerageClient ────────────────────────────────────────────────────────


class TestFakeBrokerageClientRegisterUser:
    async def test_returns_preset_user(self) -> None:
        expected = SnapTradeUser(snaptrade_user_id="snap-u", snaptrade_user_secret="snap-s")
        fake = FakeBrokerageClient(register_user_result=expected)
        result = await fake.register_user("hint-123")
        assert result == expected

    async def test_records_call(self) -> None:
        fake = FakeBrokerageClient()
        await fake.register_user("my-user-hint")
        assert "my-user-hint" in fake.register_calls


class TestFakeBrokerageClientGeneratePortalUrl:
    async def test_returns_preset_url(self) -> None:
        fake = FakeBrokerageClient(portal_url="https://example.com/connect")
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        url = await fake.generate_portal_url(user, "https://app.example.com/callback")
        assert url == "https://example.com/connect"

    async def test_records_redirect_uri(self) -> None:
        fake = FakeBrokerageClient()
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        await fake.generate_portal_url(user, "https://redirect.example.com")
        assert "https://redirect.example.com" in fake.portal_url_calls


class TestFakeBrokerageClientRevokeAuthorization:
    async def test_records_call(self) -> None:
        fake = FakeBrokerageClient()
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        await fake.revoke_authorization(user, "auth-id-xyz")
        assert (user, "auth-id-xyz") in fake.revoke_calls

    async def test_raises_when_configured(self) -> None:
        fake = FakeBrokerageClient()
        fake.should_raise_on_revoke = True
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        with pytest.raises(BrokerageApiError):
            await fake.revoke_authorization(user, "auth-id-xyz")


class TestFakeBrokerageClientGetActivities:
    async def test_returns_preset_activities(self) -> None:
        acts = [
            SnapTradeActivity(
                snaptrade_transaction_id="t1",
                activity_type="BUY",
                symbol="AAPL",
                quantity=Decimal("10"),
                price=Decimal("150"),
                currency="USD",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
        fake = FakeBrokerageClient(activities=acts)
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        result = await fake.get_activities(user, date(2026, 1, 1), date(2026, 1, 31))
        assert result == acts

    async def test_returns_empty_by_default(self) -> None:
        fake = FakeBrokerageClient()
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        result = await fake.get_activities(user, date(2026, 1, 1), date(2026, 1, 31))
        assert result == []

    async def test_raises_when_configured(self) -> None:
        fake = FakeBrokerageClient()
        fake.should_raise_on_activities = True
        user = SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s")
        with pytest.raises(BrokerageApiError):
            await fake.get_activities(user, date(2026, 1, 1), date(2026, 1, 31))
