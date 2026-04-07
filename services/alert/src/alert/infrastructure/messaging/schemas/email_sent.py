"""Avro serialiser for the ``alert.email.sent.v1`` event.

Used by ``EmailScheduler`` to produce an outbox event after a successful send.
The outbox dispatcher picks it up and publishes to Kafka (topic: alert.email.sent.v1).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import fastavro  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

_EMAIL_SENT_SCHEMA: dict[str, Any] = {
    "type": "record",
    "name": "AlertEmailSent",
    "namespace": "com.worldview",
    "fields": [
        {"name": "event_id", "type": "string"},
        {"name": "event_type", "type": "string", "default": "alert.email.sent"},
        {"name": "schema_version", "type": "int", "default": 1},
        {"name": "occurred_at", "type": "string"},
        {"name": "user_id", "type": "string"},
        {"name": "tenant_id", "type": "string"},
        {"name": "email_type", "type": "string"},
        {"name": "provider", "type": "string"},
        {"name": "provider_message_id", "type": ["null", "string"], "default": None},
        {"name": "sent_at", "type": "string"},
        {"name": "subject", "type": "string"},
    ],
}

_TOPIC = "alert.email.sent.v1"

_PARSED_SCHEMA: dict[str, Any] | None = None


def _get_parsed_schema() -> dict[str, Any]:
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.parse_schema(_EMAIL_SENT_SCHEMA)  # type: ignore[assignment]
    return _PARSED_SCHEMA  # type: ignore[return-value]


def serialize_email_sent(
    event_id: str,
    user_id: UUID,
    tenant_id: UUID,
    email_type: str,
    provider: str,
    sent_at: str,
    subject: str,
    occurred_at: str,
    provider_message_id: str | None = None,
) -> bytes:
    """Serialize an ``alert.email.sent`` event to schemaless Avro bytes.

    Args:
        event_id: UUIDv7 string for this event.
        user_id: User who received the email.
        tenant_id: Tenant context.
        email_type: ``weekly_digest`` | ``triggered_digest``.
        provider: Adapter name (``resend`` | ``sendgrid`` | ``smtp``).
        sent_at: ISO-8601 UTC timestamp of when the email was sent.
        subject: Email subject line.
        occurred_at: ISO-8601 UTC timestamp of the event occurrence.
        provider_message_id: Optional provider-assigned message ID.

    Returns:
        Schemaless Avro bytes suitable for ``OutboxEventModel.payload_avro``.
    """
    record = {
        "event_id": event_id,
        "event_type": "alert.email.sent",
        "schema_version": 1,
        "occurred_at": occurred_at,
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "email_type": email_type,
        "provider": provider,
        "provider_message_id": provider_message_id,
        "sent_at": sent_at,
        "subject": subject,
    }
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, _get_parsed_schema(), record)
    return buf.getvalue()


EMAIL_SENT_TOPIC = _TOPIC
"""Kafka topic for alert.email.sent.v1 events."""
