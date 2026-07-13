"""Unit test: the 4 deeper-stream event_types are registered in the outbox
value-serializer (PLAN-0056 Wave B3).

The ``OutboxEventValueSerializer`` routes on the outbox ``event_type`` column, so
each new stream's discriminator MUST be a key or the dispatcher raises KeyError
when it tries to serialize a deeper-stream outbox row.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from content_ingestion.infrastructure.messaging.outbox.dispatcher import ContentIngestionOutboxDispatcher

pytestmark = pytest.mark.unit


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.outbox_poll_interval_seconds = 1.0
    settings.outbox_lease_seconds = 10
    settings.outbox_batch_size = 20
    settings.outbox_max_attempts = 3
    settings.kafka_bootstrap_servers = "localhost:9092"
    settings.kafka_schema_registry_url = "http://localhost:8081"
    settings.kafka_schema_registry_basic_auth = ""
    return settings


def _capture_topic_map() -> dict:
    """Build the value serializer with all network I/O patched; return its map."""
    dispatcher = ContentIngestionOutboxDispatcher(settings=_make_settings(), session_factory=MagicMock())
    captured: dict = {}

    class _CapturingSerializer:
        def __init__(self, topic_map: dict) -> None:
            captured.update(topic_map)

    with (
        patch.object(dispatcher, "_build_schema_registry_client", return_value=MagicMock()),
        patch(
            "content_ingestion.infrastructure.messaging.outbox.dispatcher.build_avro_serializer",
            return_value=MagicMock(),
        ),
        patch(
            "content_ingestion.infrastructure.messaging.outbox.dispatcher.OutboxEventValueSerializer",
            side_effect=_CapturingSerializer,
        ),
    ):
        try:
            dispatcher._get_value_serializer()
        except Exception:  # noqa: S110 — capturing serializer intentionally raises
            pass
    return captured


@pytest.mark.parametrize(
    "event_type",
    [
        "market.prediction.event",
        "market.prediction.history",
        "market.prediction.trade",
        "market.prediction.oi",
    ],
)
def test_deeper_stream_event_type_registered(event_type: str) -> None:
    topic_map = _capture_topic_map()
    assert event_type in topic_map, f"{event_type!r} must be registered in OutboxEventValueSerializer"


def test_existing_event_types_still_registered() -> None:
    """Regression: the new registrations must not drop the existing ones."""
    topic_map = _capture_topic_map()
    for existing in ("content.article.raw.v1", "market.prediction.snapshot", "content.document.deleted.v1"):
        assert existing in topic_map
