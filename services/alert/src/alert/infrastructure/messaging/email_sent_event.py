"""Avro serialiser for the ``alert.email.sent.v1`` event.

Used by ``EmailScheduler`` to produce an outbox event after a successful send.
The outbox dispatcher picks it up and publishes to Kafka (topic: alert.email.sent.v1).

C-04: Schema is loaded from the canonical .avsc file in ``infra/kafka/schemas/``
rather than being defined inline.  All Avro schemas MUST live in the shared
schema directory — defining schemas inline in service code is a pattern to avoid
because it duplicates the source of truth and can drift from the canonical version.
See BUG_PATTERNS.md §BP-119 (schema inline drift).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fastavro  # type: ignore[import-untyped]
import fastavro.schema  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

# Resolve schema path relative to this file's location in the repo tree.
# Layout: services/alert/src/alert/infrastructure/messaging/email_sent_event.py
#                                                              ^ parents[0]
# parents[6] = repo root
_SCHEMA_PATH = Path(__file__).parents[6] / "infra" / "kafka" / "schemas" / "alert.email.sent.v1.avsc"

_TOPIC = "alert.email.sent.v1"

_PARSED_SCHEMA: dict[str, Any] | None = None


def _get_parsed_schema() -> dict[str, Any]:
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.schema.load_schema(_SCHEMA_PATH)  # type: ignore[assignment, arg-type]
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
    ----
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
    -------
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
