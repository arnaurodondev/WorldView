"""Unit tests for ArticleConsumer message parsing."""

from __future__ import annotations

import pytest
from content_store.infrastructure.consumer.article_consumer import _parse_raw_event

pytestmark = pytest.mark.unit


class TestParseRawEvent:
    def test_parses_full_event(self) -> None:
        value = {
            "event_id": "evt-001",
            "doc_id": "doc-001",
            "source_type": "eodhd",
            "source_url": "https://example.com",
            "minio_bronze_key": "bronze/key",
            "content_hash": "abc123",
            "title": "Test",
            "published_at": "2026-03-01T00:00:00Z",
            "is_backfill": True,
        }
        event = _parse_raw_event(value)
        assert event.event_id == "evt-001"
        assert event.doc_id == "doc-001"
        assert event.source_type == "eodhd"
        assert event.source_url == "https://example.com"
        assert event.minio_bronze_key == "bronze/key"
        assert event.content_hash == "abc123"
        assert event.title == "Test"
        assert event.published_at == "2026-03-01T00:00:00Z"
        assert event.is_backfill is True

    def test_handles_null_optional_fields(self) -> None:
        value = {
            "event_id": "evt-002",
            "doc_id": "doc-002",
            "source_type": "finnhub",
            "minio_bronze_key": "key",
            "content_hash": "hash",
        }
        event = _parse_raw_event(value)
        assert event.source_url is None
        assert event.title is None
        assert event.published_at is None
        assert event.is_backfill is False

    def test_coerces_types(self) -> None:
        value = {
            "event_id": 123,
            "doc_id": 456,
            "source_type": "manual",
            "minio_bronze_key": "key",
            "content_hash": "hash",
        }
        event = _parse_raw_event(value)
        assert event.event_id == "123"
        assert event.doc_id == "456"
