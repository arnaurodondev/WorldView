"""Unit tests for ContentIngestionOutboxDispatcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from content_ingestion.infrastructure.messaging.outbox.dispatcher import ContentIngestionOutboxDispatcher

pytestmark = pytest.mark.unit


class TestContentIngestionOutboxDispatcher:
    def _make_settings(self) -> MagicMock:
        settings = MagicMock()
        settings.outbox_poll_interval_seconds = 1.0
        settings.outbox_lease_seconds = 10
        settings.outbox_batch_size = 20
        settings.outbox_max_attempts = 3
        settings.kafka_bootstrap_servers = "localhost:9092"
        settings.kafka_schema_registry_url = "http://localhost:8081"
        settings.kafka_schema_registry_basic_auth = ""
        return settings

    def test_get_producer_builds_once_and_caches(self) -> None:
        settings = self._make_settings()
        session_factory = MagicMock()
        dispatcher = ContentIngestionOutboxDispatcher(settings=settings, session_factory=session_factory)

        fake_serializer = MagicMock()
        fake_producer = MagicMock()

        with (
            patch.object(dispatcher, "_get_value_serializer", return_value=fake_serializer) as mock_get_ser,
            patch(
                "content_ingestion.infrastructure.messaging.outbox.dispatcher.build_serializing_producer",
                return_value=fake_producer,
            ) as mock_build,
        ):
            p1 = dispatcher.get_producer()
            p2 = dispatcher.get_producer()

        assert p1 is fake_producer
        assert p2 is fake_producer
        mock_get_ser.assert_called_once()
        mock_build.assert_called_once()

    def test_get_serializer_returns_outbox_value_serializer(self) -> None:
        settings = self._make_settings()
        dispatcher = ContentIngestionOutboxDispatcher(settings=settings, session_factory=MagicMock())
        fake_serializer = MagicMock()

        with patch.object(dispatcher, "_get_value_serializer", return_value=fake_serializer):
            result = dispatcher.get_serializer("content.article.raw.v1")

        assert result is fake_serializer

    # ── PLAN-0086 Wave E-2: content.document.deleted.v1 topic registration ─────

    def test_deleted_topic_registered_in_value_serializer(self) -> None:
        """content.document.deleted.v1 must be in OutboxEventValueSerializer.

        T-E-2-02: Validates that _get_value_serializer() passes the deletion
        topic to OutboxEventValueSerializer so that dispatching a
        content.document.deleted.v1 outbox event does not raise KeyError.

        Strategy: patch _build_schema_registry_client and build_avro_serializer
        to avoid real network I/O, capture the topic_map passed to
        OutboxEventValueSerializer, then assert the key is present.

        SchemaRegistryClient is imported inside _build_schema_registry_client
        (deferred import) — we patch _build_schema_registry_client directly
        instead of patching the module-level attribute.
        """
        settings = self._make_settings()
        dispatcher = ContentIngestionOutboxDispatcher(settings=settings, session_factory=MagicMock())

        # Capture the topic_map dict passed to OutboxEventValueSerializer.
        captured_topic_map: dict = {}

        class _CapturingSerializer:
            """Records the topic_map keys passed at construction."""

            def __init__(self, topic_map: dict) -> None:
                captured_topic_map.update(topic_map)
                # Do not call super().__init__ -- the instance won't be used.

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
            except Exception:  # noqa: S110
                # _CapturingSerializer.__init__ records the topics before the
                # dispatcher stores the result; any downstream error is fine.
                pass

        assert "content.document.deleted.v1" in captured_topic_map, (
            "OutboxEventValueSerializer must include 'content.document.deleted.v1' "
            "so that deletion events can be dispatched without KeyError."
        )
