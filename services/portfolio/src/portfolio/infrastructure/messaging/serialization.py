"""Build per-event-type Avro serializers and Kafka headers for the outbox.

F-DP1-08 (audit 2026-04-29): the portfolio service publishes 14 distinct
event types (tenant.created, user.created, portfolio.created, …) onto a
single Kafka topic ``portfolio.events.v1``. Confluent's default
``TopicNameStrategy`` registers ALL writer schemas under the single subject
``portfolio.events.v1-value`` — but each event_type has a DIFFERENT Avro
record (different namespace + record name + fields). So registration
failed with ``NAME_MISMATCH`` for every event after the first.

Fix: use the project's ``topic_event_type_subject_name_strategy`` (lives in
``libs/messaging/kafka/serializer.py``) so each event_type registers under
its own subject ``portfolio.events.v1-<event_type>`` (e.g.
``portfolio.events.v1-tenant.created``). This is the standard pattern when
multiple event types share one topic. No external consumer reads
``portfolio.events.v1`` today, so changing the subject-naming strategy is
safe — the topic stays the same, only the Schema Registry layout changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).parent / "schemas"

_AVSC_MAP: dict[str, str] = {
    "tenant.created": "tenant.created.v1.avsc",
    "tenant.status_changed": "tenant.status_changed.v1.avsc",
    "user.created": "user.created.v1.avsc",
    "user.status_changed": "user.status_changed.v1.avsc",
    "portfolio.created": "portfolio.created.v1.avsc",
    "portfolio.renamed": "portfolio.renamed.v1.avsc",
    "portfolio.archived": "portfolio.archived.v1.avsc",
    "transaction.recorded": "transaction.recorded.v1.avsc",
    "holding.changed": "holding.changed.v1.avsc",
    "instrument_ref.created": "instrument_ref.created.v1.avsc",
    "watchlist.created": "watchlist.created.v1.avsc",
    "watchlist.deleted": "watchlist.deleted.v1.avsc",
    "watchlist.item_added": "watchlist.item_added.v1.avsc",
    "watchlist.item_deleted": "watchlist.item_deleted.v1.avsc",
    "portfolio.holding.recompute_requested": "portfolio_holding_recompute_requested.v1.avsc",
}


def _subject_per_event_type(event_type: str) -> Any:
    """Return a confluent subject_name_strategy bound to *event_type*.

    The Confluent serializer's ``subject.name.strategy`` callable signature
    is ``(SerializationContext, record_name) -> str``. Confluent only
    knows the Avro record name (e.g. ``TenantStatusChanged``) — but our
    routing key is ``event_type`` (e.g. ``tenant.status_changed``). We
    therefore close over ``event_type`` so each serializer reports a
    distinct subject regardless of the underlying record name.
    """

    def strategy(ctx: Any, _record_name: Any) -> str:
        topic: str = ctx.topic  # type: ignore[attr-defined]
        # Subject pattern: ``<topic>-<event_type>``. This isolates each
        # event type's schema evolution from the others while keeping a
        # single Kafka topic for ordering.
        return f"{topic}-{event_type}"

    return strategy


def headers_for_event(event_type: str) -> list[tuple[str, bytes]]:
    """Return Kafka message headers for *event_type*."""
    return [
        ("content-type", b"application/avro"),
        ("event-type", event_type.encode()),
    ]


def build_outbox_event_serializers(
    schema_registry_client: Any,
) -> dict[str, Any]:
    """Build a mapping of event_type → AvroSerializer.

    Args:
    ----
        schema_registry_client: Confluent SchemaRegistryClient instance.

    Returns:
    -------
        dict mapping event_type strings to AvroSerializer callables.

    """
    from confluent_kafka.schema_registry.avro import AvroSerializer  # type: ignore[import-untyped]

    serializers: dict[str, Any] = {}
    for event_type, avsc_file in _AVSC_MAP.items():
        schema_path = _SCHEMA_DIR / avsc_file
        schema_str = schema_path.read_text()
        # F-DP1-08: pin a per-event subject so each writer schema lives in
        # its own subject under the registry. ``auto.register.schemas`` is
        # left at the default (``True``) for the dev/test compose stack —
        # the pre-registered union schema in
        # ``infra/kafka/schemas/portfolio.events.v1.avsc`` (subject v1) is
        # left in place for backward read-only access but is no longer
        # the authoritative writer schema for new messages.
        serializer = AvroSerializer(
            schema_registry_client=schema_registry_client,
            schema_str=schema_str,
            conf={
                "subject.name.strategy": _subject_per_event_type(event_type),
            },
        )
        serializers[event_type] = serializer
    return serializers
