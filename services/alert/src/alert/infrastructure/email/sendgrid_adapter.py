"""SendGrid v3 email adapter for the Alert service (S10).

Calls ``POST https://api.sendgrid.com/v3/mail/send`` using ``httpx.AsyncClient``.
Raises ``EmailProviderError`` on any non-2xx response or transport failure.
"""

from __future__ import annotations

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError

from alert.domain.email_provider import EmailProviderError

logger = structlog.get_logger(__name__)

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class SendGridEmailAdapter:
    """Sends email via the SendGrid v3 HTTP API."""

    def __init__(self, api_key: str, client: AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client or AsyncClient(timeout=30.0)

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
    ) -> str:
        """Send an email via SendGrid.

        Returns:
            The SendGrid message ID from the ``X-Message-Id`` response header,
            or an empty string if the header is absent.

        Raises:
            EmailProviderError: On any non-2xx HTTP response or transport error.
        """
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": from_address},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body},
            ],
        }
        try:
            resp = await self._client.post(
                _SENDGRID_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            message_id: str = resp.headers.get("X-Message-Id", "") or ""
            logger.debug("sendgrid_email_sent", to=to, message_id=message_id)
            return message_id
        except HTTPStatusError as exc:
            logger.warning("sendgrid_send_failed", to=to, status=exc.response.status_code)
            raise EmailProviderError(f"SendGrid API error {exc.response.status_code}: {exc.response.text}") from exc
        except RequestError as exc:
            logger.warning("sendgrid_transport_error", to=to, error=str(exc))
            raise EmailProviderError(f"SendGrid transport error: {exc}") from exc
