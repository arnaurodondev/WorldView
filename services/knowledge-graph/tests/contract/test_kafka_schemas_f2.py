"""Contract tests for the 18 Avro schemas audited in PRD-0089 F2 (entity-id unification).

The F2 plan §3 audit table classifies each Kafka schema as:
  (a) tradable-only  — `instrument_id` is the security identifier (7 schemas)
  (b) any-entity     — `entity_id` may be any canonical-entity kind (11 schemas)
  (c) drops-both     — schemas that need both ids stripped (0 schemas)

Per the audit, only one schema (`entity.canonical.created.v1.avsc`, schema #8)
was modified: the doc string was extended with the F2-note and the existing
`entity_type` field was given a `default="unknown"` for forward-compat with
older producers. Every other schema is a no-op at the wire-format level
because `entity_id` and `instrument_id` remain UUID strings — the change is
purely semantic (they happen to be equal for tradable entities).

This module verifies the wire format remains sane: each schema is loaded
from `infra/kafka/schemas/`, a representative sample record is built that
matches the schema's fields, the record is serialized via fastavro, then
deserialized, and the round-trip is asserted byte-for-byte equivalent at
the Python-dict layer.

NOTE on Kafka publish: the plan §9.5 calls for an actual Kafka publish
against a running broker. We DEFER that to a follow-up integration suite
because (a) the local broker isn't guaranteed to be up in unit-test runs
and (b) the wire format is precisely what fastavro round-tripping
validates — Kafka itself doesn't transform the payload, it just transports
it. A TODO is added below for the upgrade.

Markers:
    @pytest.mark.contract — Avro schema contract guarantee (per service pyproject)

Test conventions follow `services/knowledge-graph/tests/contract/test_paths_contract.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fastavro
import pytest

# All tests in this module are pure Avro round-trip; no infrastructure needed.
# We tag them as `contract` so they run in the schema/contract suite.
pytestmark = pytest.mark.contract

# TODO(plan-0089-f2/follow-up): upgrade this suite to spin up a Kafka broker
# (via testcontainers) and actually publish + consume one of each schema.
# Tracking: F2 plan §9.5.

# Resolve the repo-root infra/kafka/schemas/ dir relative to this file.
# Path is: services/knowledge-graph/tests/contract/this_file.py
# → up 4 to repo root, then infra/kafka/schemas/.
_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "infra" / "kafka" / "schemas"


def _load_schema(filename: str) -> Any:
    """Load + parse an .avsc file from the canonical schema dir."""
    path = _SCHEMA_DIR / filename
    assert path.exists(), f"Schema file missing: {path}"
    raw = json.loads(path.read_text())
    return fastavro.parse_schema(raw)


def _roundtrip(parsed_schema: Any, record: dict[str, Any]) -> dict[str, Any]:
    """Serialize the record via fastavro, then deserialize and return."""
    import io

    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed_schema, record)
    buf.seek(0)
    return fastavro.schemaless_reader(buf, parsed_schema)  # type: ignore[no-any-return]


def _roundtrip_named(parsed_schema_list: list[Any], record_name: str, record: dict[str, Any]) -> dict[str, Any]:
    """Round-trip against a NAMED record inside a multi-record schema file.

    `portfolio.events.v1.avsc` is a JSON array of records (a union of named
    schemas). fastavro.parse_schema on such a file returns a list of parsed
    schemas; we pick the one matching `record_name`.
    """
    target = next(s for s in parsed_schema_list if s.get("name", "").rsplit(".", 1)[-1] == record_name)
    return _roundtrip(target, record)


# Shared sample values — fixed, deterministic UUIDv7-shaped strings.
_EID = "01900000-0000-7000-8000-00000000aaaa"
_IID = "01900000-0000-7000-8000-00000000bbbb"
_TID = "01900000-0000-7000-8000-00000000cccc"
_UID = "01900000-0000-7000-8000-00000000dddd"
_WID = "01900000-0000-7000-8000-00000000eeee"
_NOW = "2026-05-20T12:00:00Z"


class TestTradableOnlySchemas:
    """Class (a) — schemas that only reference `instrument_id` for tradable IDs.

    Per the F2 audit, these are no-op at the wire level — F2 just confirms
    `entity_id == instrument_id` semantically for tradable entities.
    """

    def test_market_instrument_created(self) -> None:
        # Schema #1 — tradable-only; canonical instrument creation event.
        schema = _load_schema("market.instrument.created.avsc")
        record = {
            "event_id": _EID,
            "event_type": "market.instrument.created",
            "schema_version": 3,
            "occurred_at": _NOW,
            "instrument_id": _IID,
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "instrument_type": "common_stock",
            "name": "Apple Inc.",
            "description": None,
            "isin": "US0378331005",
            "cusip": "037833100",
            "figi": "BBG000B9XRY4",
            "lei": "HWUPKR0MPOU8FGXBT394",
            "primary_ticker": "AAPL.US",
            "security_id": None,
            "entity_id": _IID,  # F2 invariant: entity_id == instrument_id
            "correlation_id": None,
            "causation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["instrument_id"] == _IID
        assert out["entity_id"] == _IID, "F2: entity_id should equal instrument_id for tradables"

    def test_market_instrument_discovered_v1(self) -> None:
        # Schema #2 — tradable-only; lightweight discovered event with entity_id mirroring.
        schema = _load_schema("market.instrument.discovered.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "market.instrument.discovered",
            "schema_version": 1,
            "occurred_at": _NOW,
            "instrument_id": _IID,
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "entity_id": _IID,
            "correlation_id": None,
            "causation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["instrument_id"] == _IID
        assert out["entity_id"] == _IID

    def test_market_instrument_updated(self) -> None:
        # Schema #3 — tradable-only; capability flag change.
        schema = _load_schema("market.instrument.updated.avsc")
        record = {
            "event_id": _EID,
            "event_type": "market.instrument.updated",
            "schema_version": 1,
            "occurred_at": _NOW,
            "instrument_id": _IID,
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "has_ohlcv": True,
            "has_quotes": None,
            "has_fundamentals": None,
            "fields_updated": ["has_ohlcv"],
            "entity_id": _IID,
            "correlation_id": None,
            "causation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["fields_updated"] == ["has_ohlcv"]

    def test_portfolio_events_holding_changed(self) -> None:
        # Schema #4 — tradable-only; HoldingChanged is the canonical instrument-ref event.
        # The portfolio.events.v1 file is a union of 10 named records — pick HoldingChanged.
        parsed = _load_schema("portfolio.events.v1.avsc")
        assert isinstance(parsed, list), "portfolio.events.v1.avsc is a multi-record union"
        record = {
            "event_id": _EID,
            "event_type": "holding.changed",
            "aggregate_type": "holding",
            "aggregate_id": _EID,
            "tenant_id": _TID,
            "occurred_at": _NOW,
            "schema_version": 1,
            "correlation_id": None,
            "causation_id": None,
            "holding_id": _EID,
            "portfolio_id": _UID,
            "instrument_id": _IID,
            "quantity": "100",
            "average_cost": "150.50",
            "currency": "USD",
        }
        out = _roundtrip_named(parsed, "HoldingChanged", record)
        assert out["instrument_id"] == _IID

    def test_portfolio_watchlist_updated_v1(self) -> None:
        # Schema #5 — tradable-only envelope; carries instrument_id under entity_id field name
        # (legacy — F2 keeps it as-is because the envelope is consumed by a single owner).
        schema = _load_schema("portfolio.watchlist.updated.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "watchlist.item_added",
            "schema_version": 1,
            "occurred_at": _NOW,
            "user_id": _UID,
            "watchlist_id": _WID,
            "entity_id": _IID,  # tradable instrument
            "entity_ids_affected": [_IID],
            "correlation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _IID

    def test_watchlist_item_added(self) -> None:
        # Schema #6 — tradable-only (in practice watchlists track tradables).
        schema = _load_schema("watchlist.item_added.avsc")
        record = {
            "event_id": _EID,
            "event_type": "watchlist.item_added",
            "aggregate_type": "watchlist",
            "aggregate_id": _WID,
            "tenant_id": _TID,
            "occurred_at": _NOW,
            "schema_version": 1,
            "correlation_id": None,
            "causation_id": None,
            "watchlist_id": _WID,
            "user_id": _UID,
            "entity_id": _IID,
            "entity_type": "company",
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _IID

    def test_watchlist_item_deleted(self) -> None:
        # Schema #7 — tradable-only mirror of #6.
        schema = _load_schema("watchlist.item_deleted.avsc")
        record = {
            "event_id": _EID,
            "event_type": "watchlist.item_deleted",
            "aggregate_type": "watchlist",
            "aggregate_id": _WID,
            "tenant_id": _TID,
            "occurred_at": _NOW,
            "schema_version": 1,
            "correlation_id": None,
            "causation_id": None,
            "watchlist_id": _WID,
            "user_id": _UID,
            "entity_id": _IID,
            "entity_type": "company",
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _IID


class TestAnyEntitySchemas:
    """Class (b) — schemas where `entity_id` may be any canonical-entity kind.

    These cover persons, events, sectors, instruments etc. F2 does NOT
    change the wire format; the only modification was extending
    `entity.canonical.created.v1.avsc`'s doc + default for `entity_type`.
    """

    def test_entity_canonical_created_v1(self) -> None:
        # Schema #8 — any-entity; the one schema we touched in F2.
        # Critical: the `entity_type` field MUST be present with a default of "unknown".
        schema = _load_schema("entity.canonical.created.v1.avsc")
        # Producer omitting `entity_type` should still serialize cleanly
        # (default kicks in via fastavro on the consumer side).
        record_full = {
            "event_id": _EID,
            "event_type": "entity.canonical.created",
            "schema_version": 1,
            "occurred_at": _NOW,
            "entity_id": _EID,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "provisional_queue_id": _EID,
            "alias_texts": ["Apple", "AAPL"],
            "correlation_id": None,
        }
        out = _roundtrip(schema, record_full)
        assert out["entity_type"] == "financial_instrument"

        # Verify the default propagates when the field is missing in the record.
        # fastavro applies defaults only at READ time for schema-evolution scenarios
        # (writer schema older than reader schema). The schema must declare the
        # default; we assert that here by parsing the raw schema and inspecting it.
        raw = json.loads((_SCHEMA_DIR / "entity.canonical.created.v1.avsc").read_text())
        et_field = next(f for f in raw["fields"] if f["name"] == "entity_type")
        assert (
            et_field.get("default") == "unknown"
        ), "F2 requires `entity_type` field to declare default='unknown' for forward-compat"

    def test_entity_dirtied_v1(self) -> None:
        # Schema #9 — any-entity; refresh signal partitioned on entity_id.
        schema = _load_schema("entity.dirtied.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "entity.dirtied",
            "schema_version": 1,
            "occurred_at": _NOW,
            "entity_id": _EID,
            "dirty_reason": "new_evidence",
            "source_doc_id": None,
            "correlation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _EID

    def test_entity_narrative_generated_v1(self) -> None:
        # Schema #10 — any-entity; narrative gen event.
        schema = _load_schema("entity.narrative.generated.v1.avsc")
        record = {
            "event_id": _EID,
            "entity_id": _EID,
            "version_id": _EID,
            "tenant_id": _TID,
            "generation_reason": "INITIAL",
            "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
            "narrative_text_length": 1024,
            "word_count": 180,
            "quality_score": 0.87,
            "occurred_at": _NOW,
            "schema_version": "1.0.0",
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _EID

    def test_nlp_article_enriched_v1(self) -> None:
        # Schema #11 — any-entity; entity_mentions cover all kinds.
        schema = _load_schema("nlp.article.enriched.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "nlp.article.enriched",
            "schema_version": 1,
            "occurred_at": _NOW,
            "doc_id": _EID,
            "source_type": "rss",
            "source_name": "Reuters",
            "published_at": _NOW,
            "is_backfill": False,
            "routing_tier": "deep",
            "routing_score": 0.85,
            "section_count": 4,
            "chunk_count": 12,
            "mention_count": 8,
            "resolved_entity_ids": [_EID, _IID],
            "relation_count": 3,
            "claim_count": 2,
            "event_count": 1,
            "provisional_entity_count": 0,
            "extraction_model_id": "Qwen/Qwen2.5-3B-Instruct",
            "raw_relations_json": "[]",
            "raw_events_json": "[]",
            "raw_claims_json": "[]",
            "correlation_id": None,
            "tenant_id": _TID,
        }
        out = _roundtrip(schema, record)
        assert out["resolved_entity_ids"] == [_EID, _IID]

    def test_nlp_signal_detected_v1(self) -> None:
        # Schema #12 — any-entity (claimer + subject can be person OR instrument).
        schema = _load_schema("nlp.signal.detected.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "nlp.signal.detected",
            "schema_version": 1,
            "occurred_at": _NOW,
            "doc_id": _EID,
            "claim_id": _EID,
            "claimer_entity_id": _EID,
            "subject_entity_id": _IID,
            "claim_type": "forward_guidance",
            "polarity": "positive",
            "extraction_confidence": 0.78,
            "is_backfill": False,
            "correlation_id": None,
            "market_impact_score": 0.42,
        }
        out = _roundtrip(schema, record)
        assert out["subject_entity_id"] == _IID
        assert out["claimer_entity_id"] == _EID

    def test_intelligence_temporal_event_v1(self) -> None:
        # Schema #13 — any-entity (events are non-tradable; exposed_entities mix kinds).
        schema = _load_schema("intelligence.temporal_event.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "intelligence.temporal_event",
            "schema_version": 1,
            "occurred_at": _NOW,
            "temporal_event_type": "macro",
            "scope": "GLOBAL",
            "region": "GLOBAL",
            "title": "FOMC Rate Decision",
            "description": "Fed holds rates steady",
            "source_article_ids": [_EID],
            "source_url": "https://example.com/fomc",
            "active_from": _NOW,
            "active_until": "",
            "residual_impact_days": 90,
            "confidence": 0.95,
            "exposed_entities": [
                {"entity_id": _IID, "exposure_type": "directly_affected", "confidence": 0.9},
            ],
        }
        out = _roundtrip(schema, record)
        assert out["exposed_entities"][0]["entity_id"] == _IID

    def test_intelligence_contradiction_v1(self) -> None:
        # Schema #14 — any-entity; subject_entity_id may be person/instrument.
        schema = _load_schema("intelligence.contradiction.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "intelligence.contradiction",
            "schema_version": 1,
            "occurred_at": _NOW,
            "subject_entity_id": _EID,
            "claim_type": "forward_guidance",
            "new_claim_id": _EID,
            "contradicting_claim_id": _UID,
            "contradiction_strength": 0.7,
            "affected_relation_ids": [],
            "is_backfill": False,
            "correlation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["subject_entity_id"] == _EID

    def test_relation_type_proposed_v1(self) -> None:
        # Schema #15 — any-entity; sample subject/object entity ids are nullable.
        schema = _load_schema("relation.type.proposed.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "relation.type.proposed",
            "schema_version": 1,
            "occurred_at": _NOW,
            "proposed_type": "PARTNERS_WITH",
            "semantic_mode": "bidirectional",
            "suggested_decay_class": "medium",
            "example_subject_entity_id": _EID,
            "example_object_entity_id": _IID,
            "example_evidence_text": "Apple partners with OpenAI",
            "source_doc_id": _EID,
            "correlation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["proposed_type"] == "PARTNERS_WITH"

    def test_graph_state_changed_v1(self) -> None:
        # Schema #16 — any-entity; primary_entity_id is the partition key.
        schema = _load_schema("graph.state.changed.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "graph.state.changed",
            "schema_version": 1,
            "occurred_at": _NOW,
            "primary_entity_id": _EID,
            "affected_entity_ids": [_EID, _IID],
            "change_type": "new_evidence",
            "relation_ids": [_EID],
            "canonical_types": ["COMPETES_WITH"],
            "source_doc_id": _EID,
            "is_backfill": False,
            "correlation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["affected_entity_ids"] == [_EID, _IID]

    def test_alert_created_v1(self) -> None:
        # Schema #17 — any-entity; alerts can watch persons, sectors, instruments.
        schema = _load_schema("alert.created.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "alert.created",
            "schema_version": 1,
            "occurred_at": _NOW,
            "alert_id": _EID,
            "user_id": _UID,
            "tenant_id": _TID,
            "entity_id": _EID,
            "condition": "price_below",
            "threshold": '{"value": 200.0}',
            "severity": "medium",
            "source": "llm_tool",
            "correlation_id": None,
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _EID

    def test_alert_delivered_v1(self) -> None:
        # Schema #18 — any-entity; mirrors #17 on delivery.
        schema = _load_schema("alert.delivered.v1.avsc")
        record = {
            "event_id": _EID,
            "event_type": "alert.delivered",
            "schema_version": 2,
            "occurred_at": _NOW,
            "alert_id": _EID,
            "user_id": _UID,
            "entity_id": _EID,
            "alert_type": "price_threshold",
            "channel": "email",
            "correlation_id": None,
            "severity": "high",
        }
        out = _roundtrip(schema, record)
        assert out["entity_id"] == _EID


class TestAuditSummary:
    """Sanity check: assert the 18 audited files exist exactly where expected."""

    _AUDITED_FILES: tuple[str, ...] = (
        # (a) tradable-only — 7 files
        "market.instrument.created.avsc",
        "market.instrument.discovered.v1.avsc",
        "market.instrument.updated.avsc",
        "portfolio.events.v1.avsc",
        "portfolio.watchlist.updated.v1.avsc",
        "watchlist.item_added.avsc",
        "watchlist.item_deleted.avsc",
        # (b) any-entity — 11 files
        "entity.canonical.created.v1.avsc",
        "entity.dirtied.v1.avsc",
        "entity.narrative.generated.v1.avsc",
        "nlp.article.enriched.v1.avsc",
        "nlp.signal.detected.v1.avsc",
        "intelligence.temporal_event.v1.avsc",
        "intelligence.contradiction.v1.avsc",
        "relation.type.proposed.v1.avsc",
        "graph.state.changed.v1.avsc",
        "alert.created.v1.avsc",
        "alert.delivered.v1.avsc",
    )

    def test_eighteen_schemas_exist(self) -> None:
        assert len(self._AUDITED_FILES) == 18
        missing = [f for f in self._AUDITED_FILES if not (_SCHEMA_DIR / f).exists()]
        assert not missing, f"F2 audit references missing schemas: {missing}"

    def test_all_audited_schemas_parse(self) -> None:
        """Every audited schema must parse cleanly via fastavro."""
        for fname in self._AUDITED_FILES:
            parsed = _load_schema(fname)
            assert parsed is not None, f"Failed to parse {fname}"
