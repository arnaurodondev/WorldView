"""Contract tests for the alert.email.sent.v1 Avro schema.

Validates:
  - Schema file is valid JSON and parseable by fastavro
  - All required fields from PRD-0016 §6.3 are present
  - ``provider_message_id`` is a nullable union (``["null", "string"]``)
  - ``serialize_email_sent()`` produces bytes that round-trip cleanly
  - Schema forward-compatibility: adding a new optional field does not break readers
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import fastavro  # type: ignore[import-untyped]
import pytest
from alert.infrastructure.messaging.email_sent_event import (
    EMAIL_SENT_TOPIC,
    serialize_email_sent,
)

_SCHEMAS_DIR = Path(__file__).parents[4] / "infra" / "kafka" / "schemas"
_SCHEMA_FILE = _SCHEMAS_DIR / "alert.email.sent.v1.avsc"

_USER_ID = uuid.UUID("01912345-6789-7abc-8def-0123456789ab")
_TENANT_ID = uuid.UUID("01912345-6789-7abc-8def-0123456789ac")
_EVENT_ID = "01912345-6789-7abc-8def-000000000001"


def _load_schema() -> dict:
    with _SCHEMA_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


class TestEmailSentAvroSchema:
    @pytest.mark.contract
    def test_schema_file_exists(self) -> None:
        assert _SCHEMA_FILE.exists(), f"Schema file missing: {_SCHEMA_FILE}"

    @pytest.mark.contract
    def test_schema_is_valid_avro(self) -> None:
        schema = _load_schema()
        parsed = fastavro.parse_schema(schema)
        assert parsed is not None

    @pytest.mark.contract
    def test_schema_has_all_required_fields(self) -> None:
        """All 10 fields from PRD-0016 §6.3 must be present."""
        schema = _load_schema()
        field_names = {f["name"] for f in schema["fields"]}
        required = {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
            "user_id",
            "tenant_id",
            "email_type",
            "provider",
            "provider_message_id",
            "sent_at",
            "subject",
        }
        missing = required - field_names
        assert not missing, f"Missing schema fields: {missing}"

    @pytest.mark.contract
    def test_provider_message_id_is_nullable_union(self) -> None:
        """provider_message_id must be a nullable union (PRD §6.3)."""
        schema = _load_schema()
        field = next(f for f in schema["fields"] if f["name"] == "provider_message_id")
        assert isinstance(field["type"], list), "provider_message_id must be a union type"
        assert "null" in field["type"]
        assert "string" in field["type"]

    @pytest.mark.contract
    def test_schema_version_has_default_1(self) -> None:
        schema = _load_schema()
        field = next(f for f in schema["fields"] if f["name"] == "schema_version")
        assert field.get("default") == 1

    @pytest.mark.contract
    def test_namespace_is_com_worldview(self) -> None:
        schema = _load_schema()
        assert schema.get("namespace") == "com.worldview"

    @pytest.mark.contract
    def test_topic_constant_matches_expected(self) -> None:
        assert EMAIL_SENT_TOPIC == "alert.email.sent.v1"


class TestEmailSentSerialization:
    @pytest.mark.contract
    def test_serialize_returns_bytes(self) -> None:
        payload = serialize_email_sent(
            event_id=_EVENT_ID,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            email_type="weekly_digest",
            provider="resend",
            sent_at="2026-04-07T08:00:00+00:00",
            subject="Your Weekly Portfolio Risk Digest",
            occurred_at="2026-04-07T08:00:00+00:00",
        )
        assert isinstance(payload, bytes)
        assert len(payload) > 0

    @pytest.mark.contract
    def test_serialized_bytes_round_trip(self) -> None:
        """Bytes must deserialize back to identical field values."""
        sent_at = "2026-04-07T08:00:00+00:00"
        payload = serialize_email_sent(
            event_id=_EVENT_ID,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            email_type="weekly_digest",
            provider="smtp",
            sent_at=sent_at,
            subject="Your Weekly Portfolio Risk Digest",
            occurred_at=sent_at,
            provider_message_id="msg-abc-123",
        )
        schema = _load_schema()
        parsed = fastavro.parse_schema(schema)
        record = fastavro.schemaless_reader(io.BytesIO(payload), parsed)  # type: ignore[arg-type]

        assert record["event_id"] == _EVENT_ID
        assert record["user_id"] == str(_USER_ID)
        assert record["tenant_id"] == str(_TENANT_ID)
        assert record["email_type"] == "weekly_digest"
        assert record["provider"] == "smtp"
        assert record["provider_message_id"] == "msg-abc-123"
        assert record["sent_at"] == sent_at
        assert record["subject"] == "Your Weekly Portfolio Risk Digest"
        assert record["schema_version"] == 1

    @pytest.mark.contract
    def test_nullable_provider_message_id_is_accepted(self) -> None:
        """provider_message_id=None must serialize without error."""
        payload = serialize_email_sent(
            event_id=_EVENT_ID,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            email_type="weekly_digest",
            provider="resend",
            sent_at="2026-04-07T08:00:00+00:00",
            subject="Digest",
            occurred_at="2026-04-07T08:00:00+00:00",
            provider_message_id=None,
        )
        schema = _load_schema()
        parsed = fastavro.parse_schema(schema)
        record = fastavro.schemaless_reader(io.BytesIO(payload), parsed)  # type: ignore[arg-type]
        assert record["provider_message_id"] is None

    @pytest.mark.contract
    def test_forward_compatibility_extra_field(self) -> None:
        """A reader with the current schema can still read records produced by
        a future writer that adds an optional field — forward compat check.

        We simulate this by constructing a record manually with an extra field
        and verifying fastavro ignores it gracefully.
        """
        schema = _load_schema()
        future_schema = dict(schema)
        future_schema["fields"] = [
            *schema["fields"],
            {"name": "new_optional_field", "type": ["null", "string"], "default": None},
        ]
        parsed_future = fastavro.parse_schema(future_schema)
        record = {
            "event_id": _EVENT_ID,
            "event_type": "alert.email.sent",
            "schema_version": 1,
            "occurred_at": "2026-04-07T08:00:00+00:00",
            "user_id": str(_USER_ID),
            "tenant_id": str(_TENANT_ID),
            "email_type": "weekly_digest",
            "provider": "resend",
            "provider_message_id": None,
            "sent_at": "2026-04-07T08:00:00+00:00",
            "subject": "Digest",
            "new_optional_field": None,
        }
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, parsed_future, record)
        # Reader uses the current schema — it simply ignores unknown fields
        parsed_current = fastavro.parse_schema(schema)
        result = fastavro.schemaless_reader(io.BytesIO(buf.getvalue()), parsed_current)  # type: ignore[arg-type]
        assert result["event_id"] == _EVENT_ID
