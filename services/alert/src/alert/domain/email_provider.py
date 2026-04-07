"""Email provider abstraction for the Alert service (S10).

``EmailProvider`` is a structural Protocol — any class with a matching
``send()`` signature satisfies it without explicit inheritance.
``EmailProviderError`` is the single exception type that all adapters
raise on failure (wrapping underlying transport errors).
"""

from __future__ import annotations

from typing import Protocol


class EmailProviderError(Exception):
    """Raised by any EmailProvider adapter when sending fails."""


class EmailProvider(Protocol):
    """Provider-agnostic interface for sending transactional email.

    Returns the provider's message ID on success (may be empty string
    for adapters that do not provide one, e.g. SMTP/Mailhog).
    """

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
    ) -> str: ...
