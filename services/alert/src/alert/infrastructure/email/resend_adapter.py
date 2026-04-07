"""Resend.com email adapter for the Alert service (S10).

Calls ``POST https://api.resend.com/emails`` using ``httpx.AsyncClient``.
Raises ``EmailProviderError`` on any non-2xx response or transport failure.
"""

from __future__ import annotations

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError

from alert.domain.email_provider import EmailProviderError

logger = structlog.get_logger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailAdapter:
    """Sends email via the Resend.com HTTP API."""

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
        """Send an email via Resend.

        Returns
        -------
            The Resend message ID on success.

        Raises
        ------
            EmailProviderError: On any non-2xx HTTP response or transport error.

        """
        payload = {
            "from": from_address,
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        try:
            resp = await self._client.post(
                _RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data: dict[str, object] = resp.json()
            message_id = str(data.get("id", ""))
            logger.debug("resend_email_sent", to=to, message_id=message_id)
            return message_id
        except HTTPStatusError as exc:
            logger.warning("resend_send_failed", to=to, status=exc.response.status_code)
            raise EmailProviderError(f"Resend API error {exc.response.status_code}: {exc.response.text}") from exc
        except RequestError as exc:
            logger.warning("resend_transport_error", to=to, error=str(exc))
            raise EmailProviderError(f"Resend transport error: {exc}") from exc
