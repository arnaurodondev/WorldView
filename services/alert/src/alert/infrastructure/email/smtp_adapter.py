"""Async SMTP email adapter for the Alert service (S10).

Uses ``aiosmtplib`` for non-blocking SMTP.  Compatible with Mailhog in dev
(unauthenticated relay on port 1025) and authenticated SMTP relays in prod.

Returns an empty string as ``provider_message_id`` because SMTP does not
expose the server-assigned message ID in the standard send response.
"""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import structlog

from alert.domain.email_provider import EmailProviderError

logger = structlog.get_logger(__name__)


class SMTPEmailAdapter:
    """Sends email via SMTP using ``aiosmtplib``."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
    ) -> str:
        """Send an email via SMTP.

        Returns:
            Empty string (SMTP does not return a provider message ID).

        Raises:
            EmailProviderError: On any SMTP protocol or connection error.
        """
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = from_address
        message["To"] = to
        message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        smtp_kwargs: dict[str, object] = {
            "hostname": self._host,
            "port": self._port,
        }

        try:
            if self._username and self._password:
                await aiosmtplib.send(
                    message,
                    username=self._username,
                    password=self._password,
                    **smtp_kwargs,  # type: ignore[arg-type]
                )
            else:
                await aiosmtplib.send(message, **smtp_kwargs)  # type: ignore[arg-type]

            logger.debug("smtp_email_sent", to=to, host=self._host, port=self._port)
            return ""
        except aiosmtplib.SMTPException as exc:
            logger.warning("smtp_send_failed", to=to, host=self._host, error=str(exc))
            raise EmailProviderError(f"SMTP error: {exc}") from exc
        except OSError as exc:
            logger.warning("smtp_connection_error", to=to, host=self._host, error=str(exc))
            raise EmailProviderError(f"SMTP connection error: {exc}") from exc
