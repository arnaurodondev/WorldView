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

    # D-INIT-6 (2026-05-09): forward-compat regression — source_name MUST be a
    # nullable string with default null so older consumers can still process the
    # event after the field is added (the canonical R5 pattern).
    def test_source_name_is_nullable_with_null_default(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "source_name":
                # Avro union ["null", "string"] is the only forward-compatible pattern
                # for adding a string field to an existing schema.
                assert isinstance(f["type"], list)
                assert "null" in f["type"]
                assert "string" in f["type"]
                # Default MUST be the JSON null literal (Python None) so producers
                # can omit the field entirely on legacy code paths.
                assert f.get("default", "MISSING") is None
                return
        pytest.fail("source_name field missing from schema")

    def test_source_name_round_trip_through_canonical(self) -> None:
        """Producer→consumer round-trip preserves source_name (D-INIT-6 regression)."""
        original = _sample(source_name="Reuters")
        d = original.to_dict()
        # Ensure the dict carries source_name explicitly — the KG consumer reads
        # ``value.get("source_name")`` directly off the deserialized payload.
        assert d["source_name"] == "Reuters"
        round_tripped = CanonicalNlpArticleEnriched.from_dict(d)
        assert round_tripped.source_name == "Reuters"

    def test_source_name_defaults_to_none_when_omitted(self) -> None:
        """Legacy producers that don't set source_name end up with None on consume."""
        original = _sample()  # no source_name override
        assert original.source_name is None
        d = original.to_dict()
        assert d["source_name"] is None
        round_tripped = CanonicalNlpArticleEnriched.from_dict(d)
        assert round_tripped.source_name is None

    # PLAN-0056 Wave C3: forward-compat regression — source_title MUST be a
    # nullable string carrying the upstream document title (= market question for
    # Polymarket synthetic docs) so the KG can title/classify prediction events.
    def test_source_title_is_nullable_with_null_default(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "source_title":
                assert isinstance(f["type"], list)
                assert "null" in f["type"]
                assert "string" in f["type"]
                assert f.get("default", "MISSING") is None
                return
        pytest.fail("source_title field missing from schema")

    def test_source_title_round_trip_through_canonical(self) -> None:
        """Producer→consumer round-trip preserves source_title (Wave C3 regression)."""
        original = _sample(source_title="Will Company X miss Q3 earnings?")
        d = original.to_dict()
        # KG PredictionEnrichedConsumer reads ``value.get("source_title")`` directly.
        assert d["source_title"] == "Will Company X miss Q3 earnings?"
        round_tripped = CanonicalNlpArticleEnriched.from_dict(d)
        assert round_tripped.source_title == "Will Company X miss Q3 earnings?"

    def test_source_title_defaults_to_none_when_omitted(self) -> None:
        """Legacy producers that don't set source_title end up with None on consume."""
        original = _sample()  # no source_title override
        assert original.source_title is None
        d = original.to_dict()
        assert d["source_title"] is None
        round_tripped = CanonicalNlpArticleEnriched.from_dict(d)
        assert round_tripped.source_title is None


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

    # ── PLAN-0062 F-009: edge cases for decode_raw_array ──────────────────

    def test_decode_raw_array_non_list_root(self) -> None:
        """A JSON object root (not list) decodes to ``[]`` — the helper is
        forgiving so a malformed extraction does not crash the consumer.
        """
        assert decode_raw_array('{"a": 1}') == []

    def test_decode_raw_array_filters_non_dict_items(self) -> None:
        """List items that are not dicts (ints, strings, nested lists) are
        silently dropped; only dict items survive.
        """
        assert decode_raw_array('[1, 2, {"k": "v"}]') == [{"k": "v"}]

    def test_decode_raw_array_oversized_returns_empty(self) -> None:
        """A blob > 16 MiB returns ``[]`` immediately — defence-in-depth
        against poison messages.
        """
        # 17 MiB JSON list — still well-formed but over the cap.
        oversized = "[" + ",".join(['{"k":"v"}'] * 1) + "]"
        oversized = oversized + " " * (17 * 1024 * 1024)
        assert decode_raw_array(oversized) == []


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
