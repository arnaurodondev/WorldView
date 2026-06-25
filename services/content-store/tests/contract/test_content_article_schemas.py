"""Contract tests — content-store Avro seams (S4→S5 consume, S5→downstream produce).

content-store consumes ``content.article.raw.v1`` (written by S4) and produces
``content.article.stored.v1`` (consumed by S6 NLP). These are the cross-service
boundaries behind its dead-letters, so this module pins three properties:

1. **Both schemas parse** and the field sets match the code's expectations.
2. **Consume seam** — a real raw payload round-trips through Avro and
   ``_parse_raw_event`` reconstructs a ``RawArticleEvent`` with aligned fields.
3. **Produce seam** — ``_build_stored_payload`` output serialises cleanly against
   the registered ``content.article.stored.v1`` schema (no missing/extra fields).
4. **Forward-compat** — a writer record predating the ``tenant_id`` addition
   deserialises with the current reader schema, defaulting ``tenant_id`` to null.

No infra required (pure fastavro), so this is a unit-speed contract suite.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import UUID

import fastavro
import pytest
from content_store.application.use_cases.process_article import (
    RawArticleEvent,
    _build_stored_payload,
)
from content_store.domain.entities import CanonicalDocument
from content_store.infrastructure.messaging.consumers.article_consumer import _parse_raw_event

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]

# Architecture test requires a module-level pytestmark.
pytestmark = pytest.mark.contract

# ── Schema locations ─────────────────────────────────────────────────────────
# tests/contract/ → tests/ → content-store/ → services/ → repo-root → infra/...
_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "infra" / "kafka" / "schemas"
_RAW_SCHEMA_PATH = _SCHEMA_DIR / "content.article.raw.v1.avsc"
_STORED_SCHEMA_PATH = _SCHEMA_DIR / "content.article.stored.v1.avsc"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def _serialize(schema_dict: dict, record: dict) -> bytes:
    parsed = fastavro.parse_schema(schema_dict)
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, record)
    return buf.getvalue()


def _deserialize(schema_dict: dict, data: bytes) -> dict:
    parsed = fastavro.parse_schema(schema_dict)
    return fastavro.schemaless_reader(io.BytesIO(data), parsed)  # type: ignore[return-value]


def _schema_field_names(schema_dict: dict) -> set[str]:
    return {f["name"] for f in schema_dict["fields"]}


# A representative S4 raw event (all fields the producer emits).
_RAW_RECORD = {
    "event_id": str(common.ids.new_uuid7()),
    "event_type": "content.article.raw",
    "schema_version": 1,
    "occurred_at": "2026-06-22T10:00:00Z",
    "doc_id": str(common.ids.new_uuid7()),
    "source_type": "eodhd",
    "source_url": "https://news.example.com/article",
    "minio_bronze_key": "content-ingestion/eodhd/abc123/raw/v1.json",
    "content_hash": "a" * 64,
    "fetch_id": str(common.ids.new_uuid7()),
    "title": "Markets Rally on Earnings Beat",
    "published_at": "2026-06-22T09:30:00Z",
    "is_backfill": False,
    "correlation_id": None,
    "tenant_id": None,
}


class TestSchemasParse:
    def test_raw_schema_parses(self) -> None:
        assert fastavro.parse_schema(_load(_RAW_SCHEMA_PATH)) is not None

    def test_stored_schema_parses(self) -> None:
        assert fastavro.parse_schema(_load(_STORED_SCHEMA_PATH)) is not None

    def test_raw_schema_has_fields_the_consumer_reads(self) -> None:
        """Every field _parse_raw_event reads must exist in the registered schema."""
        names = _schema_field_names(_load(_RAW_SCHEMA_PATH))
        required = {
            "event_id",
            "doc_id",
            "source_type",
            "source_url",
            "minio_bronze_key",
            "content_hash",
            "title",
            "published_at",
            "is_backfill",
            "tenant_id",
        }
        assert required <= names, f"schema missing consumer-read fields: {required - names}"


class TestConsumeSeam:
    """content.article.raw.v1 → Avro round-trip → _parse_raw_event."""

    def test_raw_payload_roundtrips_and_parses_to_entity(self) -> None:
        schema = _load(_RAW_SCHEMA_PATH)
        payload = _serialize(schema, _RAW_RECORD)
        decoded = _deserialize(schema, payload)

        event = _parse_raw_event(decoded)
        assert isinstance(event, RawArticleEvent)
        assert event.event_id == _RAW_RECORD["event_id"]
        assert event.doc_id == _RAW_RECORD["doc_id"]
        assert event.minio_bronze_key == _RAW_RECORD["minio_bronze_key"]
        assert event.content_hash == _RAW_RECORD["content_hash"]
        assert event.source_type == "eodhd"
        assert event.is_backfill is False
        assert event.tenant_id is None

    def test_tenant_scoped_raw_event_preserves_tenant_id(self) -> None:
        tenant = str(common.ids.new_uuid7())
        record = {**_RAW_RECORD, "tenant_id": tenant}
        schema = _load(_RAW_SCHEMA_PATH)
        event = _parse_raw_event(_deserialize(schema, _serialize(schema, record)))
        assert event.tenant_id == tenant

    def test_raw_forward_compat_without_tenant_id(self) -> None:
        """A pre-tenant_id writer record deserialises under the current reader → tenant_id null."""
        current = _load(_RAW_SCHEMA_PATH)
        old_schema = {**current, "fields": [f for f in current["fields"] if f["name"] != "tenant_id"]}
        old_record = {k: v for k, v in _RAW_RECORD.items() if k != "tenant_id"}

        writer = fastavro.parse_schema(old_schema)
        reader = fastavro.parse_schema(current)
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, writer, old_record)
        decoded: dict = fastavro.schemaless_reader(io.BytesIO(buf.getvalue()), writer, reader)  # type: ignore[assignment]

        assert decoded["tenant_id"] is None
        # And the consumer parser tolerates the absence/null.
        assert _parse_raw_event(decoded).tenant_id is None


class TestProduceSeam:
    """_build_stored_payload → content.article.stored.v1 serialisation."""

    @staticmethod
    def _canonical_doc(*, tenant_id: UUID | None = None) -> CanonicalDocument:
        return CanonicalDocument(
            id=common.ids.new_uuid7(),
            content_hash="b" * 64,
            normalized_hash="c" * 64,
            source_type="eodhd",
            title="Markets Rally on Earnings Beat",
            word_count=3,
            published_at=common.time.utc_now(),
            dedup_result="unique",
            minio_silver_key="content-store/eodhd/def456/clean/v1.txt",
            is_backfill=False,
            tenant_id=tenant_id,
        )

    def test_stored_payload_serialises_against_schema(self) -> None:
        doc = self._canonical_doc()
        article = RawArticleEvent(
            **{
                k: _RAW_RECORD[k]
                for k in (
                    "event_id",
                    "doc_id",
                    "source_type",
                    "source_url",
                    "minio_bronze_key",
                    "content_hash",
                    "title",
                    "published_at",
                    "is_backfill",
                )
            }
        )
        payload = _build_stored_payload(doc, article)

        schema = _load(_STORED_SCHEMA_PATH)
        # Round-trip: payload must serialise + deserialise with zero schema drift.
        decoded = _deserialize(schema, _serialize(schema, payload))
        assert decoded["doc_id"] == str(doc.id)
        assert decoded["dedup_result"] == "unique"
        assert decoded["minio_silver_key"] == doc.minio_silver_key
        assert decoded["source_type"] == "eodhd"
        assert decoded["tenant_id"] is None

    def test_stored_payload_keys_match_schema_fields(self) -> None:
        """The producer payload must carry exactly the schema's field set (no missing/extra)."""
        doc = self._canonical_doc()
        article = RawArticleEvent(
            **{
                k: _RAW_RECORD[k]
                for k in (
                    "event_id",
                    "doc_id",
                    "source_type",
                    "source_url",
                    "minio_bronze_key",
                    "content_hash",
                    "title",
                    "published_at",
                    "is_backfill",
                )
            }
        )
        payload = _build_stored_payload(doc, article)
        schema_fields = _schema_field_names(_load(_STORED_SCHEMA_PATH))
        assert set(payload.keys()) == schema_fields

    def test_stored_payload_propagates_tenant_id(self) -> None:
        tenant_uuid = common.ids.new_uuid7()
        tenant = str(tenant_uuid)
        doc = self._canonical_doc(tenant_id=tenant_uuid)
        article = RawArticleEvent(
            **{
                k: _RAW_RECORD[k]
                for k in (
                    "event_id",
                    "doc_id",
                    "source_type",
                    "source_url",
                    "minio_bronze_key",
                    "content_hash",
                    "title",
                    "published_at",
                    "is_backfill",
                )
            },
            tenant_id=tenant,
        )
        payload = _build_stored_payload(doc, article)
        schema = _load(_STORED_SCHEMA_PATH)
        decoded = _deserialize(schema, _serialize(schema, payload))
        assert decoded["tenant_id"] == tenant
