"""Email provider infrastructure for the Alert service (S10).

``build_email_provider`` is the single entry point — it reads the
``ALERT_EMAIL_PROVIDER`` env var (via ``Settings``) and returns the
appropriate adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alert.infrastructure.email.resend_adapter import ResendEmailAdapter
from alert.infrastructure.email.sendgrid_adapter import SendGridEmailAdapter
from alert.infrastructure.email.smtp_adapter import SMTPEmailAdapter

if TYPE_CHECKING:
    from alert.config import Settings
    from alert.domain.email_provider import EmailProvider

__all__ = [
    "ResendEmailAdapter",
    "SMTPEmailAdapter",
    "SendGridEmailAdapter",
    "build_email_provider",
]


def build_email_provider(settings: Settings) -> EmailProvider:
    """Factory: select email adapter from ``ALERT_EMAIL_PROVIDER`` env var.

    Supported values (case-insensitive):
    - ``resend``   → :class:`ResendEmailAdapter`
    - ``sendgrid`` → :class:`SendGridEmailAdapter`
    - ``smtp``     → :class:`SMTPEmailAdapter`

    Raises
    ------
        ValueError: If the configured provider name is not recognised.

    """
    provider = settings.email_provider.lower()

    if provider == "resend":
        return ResendEmailAdapter(api_key=settings.resend_api_key)

    if provider == "sendgrid":
        return SendGridEmailAdapter(api_key=settings.sendgrid_api_key)

    if provider == "smtp":
        return SMTPEmailAdapter(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
        )

    raise ValueError(
        f"Unknown email provider {settings.email_provider!r}. Supported values: 'resend', 'sendgrid', 'smtp'.",
    )
