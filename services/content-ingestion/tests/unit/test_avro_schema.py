"""Unit tests for Avro schema alignment and roundtrip serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/content_ingestion/infrastructure/messaging/schemas"
_CANONICAL_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "infra/kafka/schemas"


class TestAvroSchemaStructure:
    def test_schema_file_exists(self) -> None:
        path = _SCHEMA_DIR / "content.article.raw.v1.avsc"
        assert path.exists(), f"Schema file not found: {path}"

    def test_schema_is_valid_json(self) -> None:
        path = _SCHEMA_DIR / "content.article.raw.v1.avsc"
        schema = json.loads(path.read_text())
        assert schema["type"] == "record"
        assert schema["namespace"] == "com.worldview"

    def test_schema_has_required_fields(self) -> None:
        """Every field in the PRD §6.3.2 must be present in the schema."""
        path = _SCHEMA_DIR / "content.article.raw.v1.avsc"
        schema = json.loads(path.read_text())
        field_names = {f["name"] for f in schema["fields"]}

        required_fields = {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
            "doc_id",
            "source_type",
            "source_url",
            "minio_bronze_key",
            "content_hash",
            "fetch_id",
            "title",
            "published_at",
            "is_backfill",
            "correlation_id",
        }

        missing = required_fields - field_names
        assert not missing, f"Missing schema fields: {missing}"

    def test_local_schema_matches_canonical(self) -> None:
        """Local copy must match infra/kafka/schemas/ canonical version."""
        local = json.loads((_SCHEMA_DIR / "content.article.raw.v1.avsc").read_text())
        canonical = json.loads((_CANONICAL_SCHEMA_DIR / "content.article.raw.v1.avsc").read_text())

        local_fields = {f["name"] for f in local["fields"]}
        canonical_fields = {f["name"] for f in canonical["fields"]}

        assert local_fields == canonical_fields, (
            f"Field mismatch — local extra: {local_fields - canonical_fields}, "
            f"canonical extra: {canonical_fields - local_fields}"
        )


class TestAvroRoundtrip:
    def test_outbox_payload_matches_schema_fields(self) -> None:
        """Verify that a sample outbox payload covers all required Avro fields."""
        import common.ids
        import common.time

        path = _SCHEMA_DIR / "content.article.raw.v1.avsc"
        schema = json.loads(path.read_text())
        schema_fields = {f["name"] for f in schema["fields"]}

        # Build a representative payload as the outbox would produce
        now = common.time.utc_now()
        payload = {
            "event_id": str(common.ids.new_uuid7()),
            "event_type": "content.article.raw",
            "schema_version": 1,
            "occurred_at": common.time.to_iso8601(now),
            "doc_id": str(common.ids.new_uuid7()),
            "source_type": "eodhd",
            "source_url": "https://example.com/article",
            "minio_bronze_key": "content-ingestion/eodhd/abc123/raw/v1.json",
            "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "fetch_id": str(common.ids.new_uuid7()),
            "title": "Test Article",
            "published_at": common.time.to_iso8601(now),
            "is_backfill": False,
            "correlation_id": None,
            "tenant_id": None,
        }

        payload_fields = set(payload.keys())
        assert payload_fields == schema_fields, (
            f"Payload/schema mismatch — missing in payload: {schema_fields - payload_fields}, "
            f"extra in payload: {payload_fields - schema_fields}"
        )
