"""Contract tests for ``CanonicalNlpSignalDetected`` ↔ ``nlp.signal.detected.v1.avsc``.

PLAN-0062 audit follow-up F-006.  Mirrors the alignment style of
``test_events_kg_provisional_queued.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.nlp.signal_detected import CanonicalNlpSignalDetected

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "nlp.signal.detected.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalNlpSignalDetected:
    base: dict[str, object] = {
        "event_id": "01900000-0000-7000-0000-000000000040",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "doc_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
        "claim_id": "01234567-89ab-7def-8012-bbbbbbbbbbbb",
        "claim_type": "forward_guidance",
        "polarity": "positive",
        "extraction_confidence": 0.87,
    }
    base.update(overrides)
    return CanonicalNlpSignalDetected(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Field alignment
# ---------------------------------------------------------------------------


class TestSchemaAlignment:
    def test_avro_schema_field_set_matches_to_dict(self) -> None:
        """Every field in the Avro schema is produced by ``to_dict``."""
        schema = _load_schema()
        avro_fields = {f["name"] for f in schema["fields"]}
        emitted = set(_sample().to_dict().keys())

        assert avro_fields == emitted, (
            f"Avro schema fields and to_dict() output diverge.\n"
            f"  In Avro only: {avro_fields - emitted}\n"
            f"  In to_dict only: {emitted - avro_fields}"
        )

    def test_nullable_fields_have_null_default(self) -> None:
        schema = _load_schema()
        nullable = {"claimer_entity_id", "subject_entity_id", "correlation_id"}
        for f in schema["fields"]:
            if f["name"] in nullable:
                assert (
                    isinstance(f["type"], list) and "null" in f["type"]
                ), f"{f['name']} must be a Avro union including 'null'"
                assert f.get("default", "MISSING") is None, f"{f['name']} must default to null"

    def test_event_type_default_matches_constant(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "event_type":
                assert f.get("default") == "nlp.signal.detected"
                return
        pytest.fail("Avro schema is missing the event_type field")

    def test_market_impact_score_defaults_zero(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "market_impact_score":
                assert f.get("default") == 0.0
                return
        pytest.fail("Avro schema is missing the market_impact_score field")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(
            claimer_entity_id="01234567-89ab-7def-8012-cccccccccccc",
            subject_entity_id="01234567-89ab-7def-8012-dddddddddddd",
            is_backfill=True,
            correlation_id="01234567-89ab-7def-8012-eeeeeeeeeeee",
            market_impact_score=0.42,
        )
        round_tripped = CanonicalNlpSignalDetected.from_dict(original.to_dict())
        assert round_tripped == original

    def test_from_dict_handles_optional_nulls(self) -> None:
        d = {
            "event_id": "01900000-0000-7000-0000-000000000040",
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "doc_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
            "claim_id": "01234567-89ab-7def-8012-bbbbbbbbbbbb",
            "claimer_entity_id": None,
            "subject_entity_id": None,
            "claim_type": "factual",
            "polarity": "neutral",
            "extraction_confidence": 0.5,
            "is_backfill": False,
            "correlation_id": None,
            "market_impact_score": 0.0,
        }
        model = CanonicalNlpSignalDetected.from_dict(d)
        assert model.claimer_entity_id is None
        assert model.subject_entity_id is None
        assert model.correlation_id is None
        # defaults baked in
        assert model.event_type == "nlp.signal.detected"
        assert model.schema_version == 1
        assert model.market_impact_score == 0.0


# ---------------------------------------------------------------------------
# Avro schema validity (round-trip via fastavro)
# ---------------------------------------------------------------------------


class TestAvroSerialization:
    def test_to_dict_serializes_with_fastavro(self) -> None:
        """to_dict() output is acceptable to fastavro.schemaless_writer."""
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample(
            claimer_entity_id="01234567-89ab-7def-8012-cccccccccccc",
            subject_entity_id="01234567-89ab-7def-8012-dddddddddddd",
            market_impact_score=0.42,
        )
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["doc_id"] == sample.doc_id
        assert decoded["claim_id"] == sample.claim_id
        assert decoded["claim_type"] == sample.claim_type
        assert decoded["polarity"] == sample.polarity
        # fastavro uses float32 for "float" type
        assert decoded["extraction_confidence"] == pytest.approx(sample.extraction_confidence, rel=1e-5)
        assert decoded["market_impact_score"] == pytest.approx(sample.market_impact_score)
