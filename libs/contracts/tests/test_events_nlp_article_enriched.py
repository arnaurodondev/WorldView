"""Contract tests for ``CanonicalNlpArticleEnriched`` ↔ ``nlp.article.enriched.v1.avsc``.

PLAN-0062 Wave B.  Mirrors the alignment style of
``test_events_kg_provisional_queued.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.nlp.article_enriched import (
    CanonicalNlpArticleEnriched,
    decode_raw_array,
    encode_raw_array,
)

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "nlp.article.enriched.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalNlpArticleEnriched:
    base = {
        "event_id": "01900000-0000-7000-0000-000000000020",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "doc_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
        "source_type": "news",
        "routing_tier": "deep",
        "routing_score": 0.81,
        "section_count": 3,
        "chunk_count": 12,
        "mention_count": 24,
        "resolved_entity_ids": ("01234567-89ab-7def-8012-345678901234",),
        "is_backfill": False,
        "relation_count": 4,
        "claim_count": 2,
        "event_count": 1,
    }
    base.update(overrides)
    return CanonicalNlpArticleEnriched(**base)  # type: ignore[arg-type]


class TestSchemaAlignment:
    def test_avro_schema_field_set_matches_to_dict(self) -> None:
        schema = _load_schema()
        avro_fields = {f["name"] for f in schema["fields"]}
        emitted = set(_sample().to_dict().keys())

        assert avro_fields == emitted, (
            f"Avro schema fields and to_dict() output diverge.\n"
            f"  In Avro only: {avro_fields - emitted}\n"
            f"  In to_dict only: {emitted - avro_fields}"
        )

    def test_raw_arrays_are_nullable_strings(self) -> None:
        schema = _load_schema()
        nullable_strings = {"raw_relations_json", "raw_events_json", "raw_claims_json"}
        seen: set[str] = set()
        for f in schema["fields"]:
            if f["name"] in nullable_strings:
                assert isinstance(f["type"], list) and "null" in f["type"] and "string" in f["type"]
                assert f.get("default", "MISSING") is None
                seen.add(f["name"])
        assert seen == nullable_strings, f"missing fields: {nullable_strings - seen}"

    def test_event_type_default_matches_constant(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "event_type":
                assert f.get("default") == "nlp.article.enriched"
                return
        pytest.fail("event_type missing from schema")


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(
            extraction_model_id="qwen-deepinfra-v1",
            raw_relations_json='[{"subject_entity_id": "x", "object_entity_id": "y", "raw_type": "owns"}]',
            correlation_id="01234567-89ab-7def-8012-bbbbbbbbbbbb",
        )
        round_tripped = CanonicalNlpArticleEnriched.from_dict(original.to_dict())
        assert round_tripped == original

    def test_encode_decode_helpers_handle_none_and_empty(self) -> None:
        assert encode_raw_array(None) is None
        assert encode_raw_array([]) is None
        assert decode_raw_array(None) == []
        assert decode_raw_array("") == []
        assert decode_raw_array("not-json") == []

    def test_encode_decode_helpers_round_trip_arrays(self) -> None:
        items = [{"a": 1}, {"b": "two"}]
        encoded = encode_raw_array(items)
        assert encoded is not None
        decoded = decode_raw_array(encoded)
        assert decoded == items


class TestAvroSerialization:
    def test_to_dict_serializes_with_fastavro(self) -> None:
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample(
            raw_relations_json=encode_raw_array([{"subject_entity_id": "x"}]),
            raw_events_json=None,
        )
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["doc_id"] == sample.doc_id
        assert decoded["routing_tier"] == "deep"
        assert decoded["raw_relations_json"] == sample.raw_relations_json
        assert decoded["raw_events_json"] is None
