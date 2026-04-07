"""Unit tests for EmailPreference domain entity and EmailProvider Protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from alert.domain.email_provider import EmailProvider, EmailProviderError
from alert.domain.entities import EmailPreference


class TestEmailPreference:
    """Tests for EmailPreference construction and invariant enforcement."""

    @pytest.mark.unit
    def test_default_construction(self) -> None:
        pref = EmailPreference(
            user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
            tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
        )
        assert pref.weekly_digest_enabled is True
        assert pref.send_day_of_week == 6
        assert pref.send_hour_utc == 8
        assert pref.email_address is None
        assert pref.last_digest_sent_at is None

    @pytest.mark.unit
    def test_explicit_construction(self) -> None:
        user_id = UUID("01912345-6789-7abc-8def-0123456789ab")
        tenant_id = UUID("01912345-6789-7abc-8def-0123456789ac")
        now = datetime.now(tz=UTC)

        pref = EmailPreference(
            user_id=user_id,
            tenant_id=tenant_id,
            weekly_digest_enabled=False,
            send_day_of_week=0,
            send_hour_utc=9,
            email_address="user@example.com",
            last_digest_sent_at=now,
        )
        assert pref.weekly_digest_enabled is False
        assert pref.send_day_of_week == 0
        assert pref.send_hour_utc == 9
        assert pref.email_address == "user@example.com"
        assert pref.last_digest_sent_at == now

    @pytest.mark.unit
    @pytest.mark.parametrize("day", [0, 1, 2, 3, 4, 5, 6])
    def test_valid_send_day_of_week(self, day: int) -> None:
        pref = EmailPreference(
            user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
            tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
            send_day_of_week=day,
        )
        assert pref.send_day_of_week == day

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_day", [-1, 7, 100, -100])
    def test_invalid_send_day_of_week_raises(self, bad_day: int) -> None:
        with pytest.raises(ValueError, match="send_day_of_week"):
            EmailPreference(
                user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
                tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
                send_day_of_week=bad_day,
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("hour", [0, 8, 12, 23])
    def test_valid_send_hour_utc(self, hour: int) -> None:
        pref = EmailPreference(
            user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
            tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
            send_hour_utc=hour,
        )
        assert pref.send_hour_utc == hour

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_hour", [-1, 24, 100])
    def test_invalid_send_hour_utc_raises(self, bad_hour: int) -> None:
        with pytest.raises(ValueError, match="send_hour_utc"):
            EmailPreference(
                user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
                tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
                send_hour_utc=bad_hour,
            )

    @pytest.mark.unit
    def test_nullable_email_address(self) -> None:
        pref = EmailPreference(
            user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
            tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
        )
        assert pref.email_address is None

        pref_with_email = EmailPreference(
            user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
            tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
            email_address="override@example.com",
        )
        assert pref_with_email.email_address == "override@example.com"

    @pytest.mark.unit
    def test_timestamps_are_set(self) -> None:
        pref = EmailPreference(
            user_id=UUID("01912345-6789-7abc-8def-0123456789ab"),
            tenant_id=UUID("01912345-6789-7abc-8def-0123456789ac"),
        )
        assert pref.created_at is not None
        assert pref.updated_at is not None
        assert pref.created_at.tzinfo is not None  # UTC-aware


class TestEmailProvider:
    """Structural tests for the EmailProvider Protocol."""

    @pytest.mark.unit
    def test_stub_satisfies_protocol(self) -> None:
        """A class with a matching send() method satisfies EmailProvider structurally."""

        class StubEmailProvider:
            async def send(
                self,
                to: str,
                subject: str,
                html_body: str,
                text_body: str,
                from_address: str,
            ) -> str:
                return "stub-message-id"

        provider: EmailProvider = StubEmailProvider()  # type: ignore[assignment]
        assert provider is not None

    @pytest.mark.unit
    def test_email_provider_error_is_exception(self) -> None:
        err = EmailProviderError("send failed: 500")
        assert isinstance(err, Exception)
        assert "500" in str(err)

    @pytest.mark.unit
    def test_email_provider_error_can_be_raised_and_caught(self) -> None:
        with pytest.raises(EmailProviderError, match="timeout"):
            raise EmailProviderError("timeout connecting to SMTP")
