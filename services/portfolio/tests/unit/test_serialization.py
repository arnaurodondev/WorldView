"""Unit tests for outbox serialization helpers."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from portfolio.application.messaging.outbox_mapper import outbox_record_to_kafka_value
from portfolio.infrastructure.messaging.serialization import headers_for_event


def test_headers_for_event_content_type() -> None:
    headers = headers_for_event("tenant.created")
    content_types = [v for k, v in headers if k == "content-type"]
    assert content_types == [b"application/avro"]


def test_headers_for_event_event_type() -> None:
    headers = headers_for_event("portfolio.archived")
    event_types = [v for k, v in headers if k == "event-type"]
    assert event_types == [b"portfolio.archived"]


def test_identity_outbox_mapper() -> None:
    payload = {"event_id": "abc", "event_type": "tenant.created"}
    assert outbox_record_to_kafka_value(payload) is payload
