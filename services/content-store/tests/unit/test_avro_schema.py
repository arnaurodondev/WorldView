"""Avro contract tests for content.article.stored.v1 schema (T-R2-3-01).

Mirrors services/content-ingestion/tests/unit/test_avro_schema.py pattern.
Verifies field-by-field alignment between _build_stored_payload() output
and the canonical Avro schema at infra/kafka/schemas/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from content_store.application.use_cases.process_article import (
    RawArticleEvent,
    _build_stored_payload,
)
from content_store.domain.entities import CanonicalDocument
from content_store.domain.enums import DedupOutcome, DocumentStatus

pytestmark = pytest.mark.unit

_CANONICAL_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "infra/kafka/schemas"
_SCHEMA_FILE = "content.article.stored.v1.avsc"


class TestAvroSchemaStructure:
    def test_schema_file_exists(self) -> None:
        path = _CANONICAL_SCHEMA_DIR / _SCHEMA_FILE
        assert path.exists(), f"Schema file not found: {path}"

    def test_schema_is_valid_json(self) -> None:
        path = _CANONICAL_SCHEMA_DIR / _SCHEMA_FILE
        schema = json.loads(path.read_text())
        assert schema["type"] == "record"
        assert schema["namespace"] == "com.worldview"
        assert schema["name"] == "ContentArticleStored"

    def test_schema_has_required_envelope_fields(self) -> None:
        """Every Avro event must have envelope fields."""
        path = _CANONICAL_SCHEMA_DIR / _SCHEMA_FILE
        schema = json.loads(path.read_text())
        field_names = {f["name"] for f in schema["fields"]}

        envelope_fields = {"event_id", "event_type", "schema_version", "occurred_at"}
        missing = envelope_fields - field_names
        assert not missing, f"Missing envelope fields: {missing}"

    def test_schema_has_required_data_fields(self) -> None:
        """All data fields from PRD must be present."""
        path = _CANONICAL_SCHEMA_DIR / _SCHEMA_FILE
        schema = json.loads(path.read_text())
        field_names = {f["name"] for f in schema["fields"]}

        data_fields = {
            "doc_id",
            "content_hash",
            "normalized_hash",
            "dedup_result",
            "minio_silver_key",
            "source_type",
            "title",
            "word_count",
            "published_at",
            "is_backfill",
            "correlation_id",
        }
        missing = data_fields - field_names
        assert not missing, f"Missing data fields: {missing}"


class TestPayloadSchemaAlignment:
    def _make_payload(self) -> dict:
        """Build a representative _build_stored_payload() output."""
        doc = CanonicalDocument(
            source_type="eodhd",
            content_hash="abc123def456",
            normalized_hash="789ghi012jkl",
            status=DocumentStatus.STORED,
            dedup_result=DedupOutcome.UNIQUE,
            minio_silver_key="content-store/canonical/test/body.json",
            word_count=150,
        )
        article = RawArticleEvent(
            event_id="evt-001",
            doc_id="doc-001",
            source_type="eodhd",
            source_url="https://example.com/article",
            minio_bronze_key="content-ingestion/eodhd/abc/raw/v1.json",
            content_hash="abc123def456",
            title="Test Article",
            published_at="2026-03-01T12:00:00Z",
            is_backfill=False,
        )
        return _build_stored_payload(doc, article)

    def test_payload_fields_match_schema_fields(self) -> None:
        """Every field in _build_stored_payload() must match an Avro schema field."""
        path = _CANONICAL_SCHEMA_DIR / _SCHEMA_FILE
        schema = json.loads(path.read_text())
        schema_fields = {f["name"] for f in schema["fields"]}

        payload = self._make_payload()
        payload_fields = set(payload.keys())

        assert payload_fields == schema_fields, (
            f"Payload/schema mismatch — missing in payload: {schema_fields - payload_fields}, "
            f"extra in payload: {payload_fields - schema_fields}"
        )

    def test_payload_field_types_compatible(self) -> None:
        """Verify payload value types are compatible with Avro field types."""
        payload = self._make_payload()

        # String fields
        for field in (
            "event_id",
            "event_type",
            "occurred_at",
            "doc_id",
            "content_hash",
            "normalized_hash",
            "dedup_result",
            "minio_silver_key",
            "source_type",
        ):
            assert isinstance(payload[field], str), f"{field} should be str, got {type(payload[field])}"

        # Int fields
        assert isinstance(payload["schema_version"], int)

        # Boolean fields
        assert isinstance(payload["is_backfill"], bool)

        # Nullable fields (str or None)
        for field in ("title", "published_at", "correlation_id"):
            assert payload[field] is None or isinstance(
                payload[field], str
            ), f"{field} should be str|None, got {type(payload[field])}"

        # Nullable int
        assert payload["word_count"] is None or isinstance(
            payload["word_count"], int
        ), f"word_count should be int|None, got {type(payload['word_count'])}"
