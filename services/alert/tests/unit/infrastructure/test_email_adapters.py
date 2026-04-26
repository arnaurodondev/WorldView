"""Unit tests for email provider adapters and build_email_provider factory."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from alert.config import Settings
from alert.domain.email_provider import EmailProviderError
from alert.infrastructure.email import (
    ResendEmailAdapter,
    SendGridEmailAdapter,
    SMTPEmailAdapter,
    build_email_provider,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "email_provider": "resend",
        "email_from_address": "noreply@example.com",
        "resend_api_key": "re_test_key",
        "sendgrid_api_key": "sg_test_key",
        "smtp_host": "localhost",
        "smtp_port": 1025,
        "s8_internal_jwt": "test-s8-token",
        "s1_internal_token": "test-s1-token",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _mock_response(
    status_code: int = 200, json_body: object = None, headers: dict[str, str] | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = f"status {status_code}"
    resp.json.return_value = json_body or {}
    resp.headers = headers or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# ResendEmailAdapter
# ---------------------------------------------------------------------------


class TestResendEmailAdapter:
    @pytest.mark.unit
    async def test_send_success_returns_message_id(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(200, json_body={"id": "resend-msg-001"}))

        adapter = ResendEmailAdapter(api_key="re_key", client=mock_client)
        msg_id = await adapter.send(
            to="user@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            text_body="Hello",
            from_address="noreply@example.com",
        )

        assert msg_id == "resend-msg-001"
        mock_client.post.assert_called_once()

    @pytest.mark.unit
    async def test_send_passes_bearer_token(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(200, json_body={"id": "x"}))

        adapter = ResendEmailAdapter(api_key="re_secret", client=mock_client)
        await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer re_secret"

    @pytest.mark.unit
    async def test_send_4xx_raises_email_provider_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(422))

        adapter = ResendEmailAdapter(api_key="re_key", client=mock_client)
        with pytest.raises(EmailProviderError, match="422"):
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_send_5xx_raises_email_provider_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(503))

        adapter = ResendEmailAdapter(api_key="re_key", client=mock_client)
        with pytest.raises(EmailProviderError, match="503"):
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_send_transport_error_raises_email_provider_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        adapter = ResendEmailAdapter(api_key="re_key", client=mock_client)
        with pytest.raises(EmailProviderError, match="transport"):
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_send_missing_id_returns_empty_string(self) -> None:
        """Resend response without 'id' field → empty string (not an error)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(200, json_body={}))

        adapter = ResendEmailAdapter(api_key="re_key", client=mock_client)
        msg_id = await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")
        assert msg_id == ""


# ---------------------------------------------------------------------------
# SendGridEmailAdapter
# ---------------------------------------------------------------------------


class TestSendGridEmailAdapter:
    @pytest.mark.unit
    async def test_send_success_returns_header_message_id(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(202, headers={"X-Message-Id": "sg-msg-999"}))

        adapter = SendGridEmailAdapter(api_key="sg_key", client=mock_client)
        msg_id = await adapter.send(
            to="user@example.com",
            subject="Test",
            html_body="<p>Hi</p>",
            text_body="Hi",
            from_address="noreply@example.com",
        )

        assert msg_id == "sg-msg-999"

    @pytest.mark.unit
    async def test_send_passes_bearer_token(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(202))

        adapter = SendGridEmailAdapter(api_key="sg_secret", client=mock_client)
        await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer sg_secret"

    @pytest.mark.unit
    async def test_send_no_message_id_header_returns_empty(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(202))

        adapter = SendGridEmailAdapter(api_key="sg_key", client=mock_client)
        msg_id = await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")
        assert msg_id == ""

    @pytest.mark.unit
    async def test_send_4xx_raises_email_provider_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(400))

        adapter = SendGridEmailAdapter(api_key="sg_key", client=mock_client)
        with pytest.raises(EmailProviderError, match="400"):
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_send_transport_error_raises_email_provider_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        adapter = SendGridEmailAdapter(api_key="sg_key", client=mock_client)
        with pytest.raises(EmailProviderError, match="transport"):
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_payload_structure(self) -> None:
        """Verify the SendGrid v3 personalizations payload shape."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_mock_response(202))

        adapter = SendGridEmailAdapter(api_key="sg_key", client=mock_client)
        await adapter.send("dest@e.com", "My Subject", "<p>H</p>", "H", "src@e.com")

        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["personalizations"][0]["to"][0]["email"] == "dest@e.com"
        assert payload["from"]["email"] == "src@e.com"
        assert payload["subject"] == "My Subject"
        types = [c["type"] for c in payload["content"]]
        assert "text/html" in types
        assert "text/plain" in types


# ---------------------------------------------------------------------------
# SMTPEmailAdapter
# ---------------------------------------------------------------------------


class TestSMTPEmailAdapter:
    @pytest.mark.unit
    async def test_send_unauthenticated_returns_empty_string(self) -> None:
        with patch("alert.infrastructure.email.smtp_adapter.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "")

            adapter = SMTPEmailAdapter(host="localhost", port=1025)
            msg_id = await adapter.send(
                to="user@example.com",
                subject="Test",
                html_body="<p>Hi</p>",
                text_body="Hi",
                from_address="noreply@example.com",
            )

        assert msg_id == ""
        mock_send.assert_called_once()

    @pytest.mark.unit
    async def test_send_authenticated_passes_credentials(self) -> None:
        with patch("alert.infrastructure.email.smtp_adapter.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "")

            adapter = SMTPEmailAdapter(
                host="smtp.example.com",
                port=587,
                username="user",
                password="secret",
            )
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["username"] == "user"
        assert call_kwargs["password"] == "secret"  # noqa: S105

    @pytest.mark.unit
    async def test_send_smtp_exception_raises_email_provider_error(self) -> None:
        import aiosmtplib as _aiosmtplib

        with patch("alert.infrastructure.email.smtp_adapter.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = _aiosmtplib.SMTPConnectError("Service unavailable")

            adapter = SMTPEmailAdapter(host="localhost", port=1025)
            with pytest.raises(EmailProviderError, match="SMTP"):
                await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_send_os_error_raises_email_provider_error(self) -> None:
        with patch("alert.infrastructure.email.smtp_adapter.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = OSError("Connection refused")

            adapter = SMTPEmailAdapter(host="localhost", port=1025)
            with pytest.raises(EmailProviderError, match="connection"):
                await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

    @pytest.mark.unit
    async def test_send_no_credentials_calls_without_username(self) -> None:
        """When username is empty, send() is called without username/password kwargs."""
        with patch("alert.infrastructure.email.smtp_adapter.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "")

            adapter = SMTPEmailAdapter(host="localhost", port=1025)
            await adapter.send("u@e.com", "s", "<b>b</b>", "b", "from@e.com")

        call_kwargs = mock_send.call_args.kwargs
        assert "username" not in call_kwargs
        assert "password" not in call_kwargs


# ---------------------------------------------------------------------------
# build_email_provider factory
# ---------------------------------------------------------------------------


class TestBuildEmailProvider:
    @pytest.mark.unit
    def test_resend_provider_selected(self) -> None:
        settings = _settings(email_provider="resend")
        provider = build_email_provider(settings)
        assert isinstance(provider, ResendEmailAdapter)

    @pytest.mark.unit
    def test_sendgrid_provider_selected(self) -> None:
        settings = _settings(email_provider="sendgrid")
        provider = build_email_provider(settings)
        assert isinstance(provider, SendGridEmailAdapter)

    @pytest.mark.unit
    def test_smtp_provider_selected(self) -> None:
        settings = _settings(email_provider="smtp")
        provider = build_email_provider(settings)
        assert isinstance(provider, SMTPEmailAdapter)

    @pytest.mark.unit
    def test_provider_name_is_case_insensitive(self) -> None:
        assert isinstance(build_email_provider(_settings(email_provider="Resend")), ResendEmailAdapter)
        assert isinstance(build_email_provider(_settings(email_provider="SMTP")), SMTPEmailAdapter)
        assert isinstance(build_email_provider(_settings(email_provider="SendGrid")), SendGridEmailAdapter)

    @pytest.mark.unit
    def test_unknown_provider_raises_value_error(self) -> None:
        settings = _settings(email_provider="mailgun")
        with pytest.raises(ValueError, match="mailgun"):
            build_email_provider(settings)

    @pytest.mark.unit
    def test_resend_adapter_receives_api_key(self) -> None:
        settings = _settings(email_provider="resend", resend_api_key="re_prod_key")
        provider = build_email_provider(settings)
        assert isinstance(provider, ResendEmailAdapter)
        assert provider._api_key == "re_prod_key"

    @pytest.mark.unit
    def test_sendgrid_adapter_receives_api_key(self) -> None:
        settings = _settings(email_provider="sendgrid", sendgrid_api_key="sg_prod_key")
        provider = build_email_provider(settings)
        assert isinstance(provider, SendGridEmailAdapter)
        assert provider._api_key == "sg_prod_key"

    @pytest.mark.unit
    def test_smtp_adapter_receives_connection_params(self) -> None:
        settings = _settings(
            email_provider="smtp",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="relay_user",
            smtp_password="relay_pass",
        )
        provider = build_email_provider(settings)
        assert isinstance(provider, SMTPEmailAdapter)
        assert provider._host == "smtp.example.com"
        assert provider._port == 465
        assert provider._username == "relay_user"
        assert provider._password == "relay_pass"  # noqa: S105
